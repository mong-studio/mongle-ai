"""Open-model + LoRA 추론 파이프라인 (RunPod Serverless 워커용).

한 이미지로 단독(엔드포인트당 LoRA 1개) 또는 멀티-LoRA 를 모두 지원한다.
베이스 모델은 VRAM 에 한 번만 올라가고, 요청의 adapter 이름으로 LoRA 를 고른다.
LoRA repo 는 환경변수로 주입하며, 설정된 어댑터만 등록한다:
  LORA_PLANNER_REPO    — adapter="planner"  (todo)
  LORA_CHARACTER_REPO  — adapter="character" (캐릭터 페르소나)
  LORA_QUEST_REPO      — adapter="quest"    (퀘스트 문장)
  LORA_FEED_REPO       — adapter="feed"     (피드 캡션)
"""
from __future__ import annotations

import os
from typing import Any

from huggingface_hub import snapshot_download
from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest

# 베이스 모델은 빌드/배포 시 env(LLM_BASE_MODEL)로 고른다. 기본은 character용 Qwen.
# 같은 이미지를 planner(EXAONE)·character(Qwen) 엔드포인트가 공유하므로 하드코딩 금지.
# revision: 베이스를 바꾸면 Qwen 전용 핀이 안 맞으니 함께 주입한다. 빈 값이면 latest.
_BASE_MODEL = os.environ.get("LLM_BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct").strip()
_BASE_MODEL_REVISION = (
    os.environ.get(
        "LLM_BASE_MODEL_REVISION", "a09a35458c702b33eeacc393d103063234e8bc28"
    ).strip()
    or None
)


def _turn_stop_token_ids(tokenizer) -> list[int]:
    """턴 종료 토큰을 베이스 모델에 맞춰 고른다.

    vLLM 기본 stop 은 eos 뿐이라, Qwen 의 <|im_end|> 처럼 eos 가 아닌 턴 종료 토큰에서
    안 멈추고 system few-shot(입력:/출력:) 패턴을 이어받아 가짜 턴을 계속 생성(runaway)한다.
    모델별 턴 종료 토큰(Qwen=<|im_end|>, EXAONE=[|endofturn|])을 vocab 에 실재하는 것만 추가하고,
    eos 도 항상 포함한다(convert_tokens_to_ids 가 미존재 토큰에 unk id 를 주어 오정지하는 것 방지).
    """
    vocab = tokenizer.get_vocab()
    ids: list[int] = [
        tokenizer.convert_tokens_to_ids(tok)
        for tok in ("<|im_end|>", "[|endofturn|]")
        if tok in vocab
    ]
    eos = tokenizer.eos_token_id
    if eos is not None and eos not in ids:
        ids.append(eos)
    return ids

# 어댑터 이름 → LoRA HF repo 를 지정하는 환경변수
_ADAPTER_ENV = {
    "planner": "LORA_PLANNER_REPO",
    "character": "LORA_CHARACTER_REPO",
    "quest": "LORA_QUEST_REPO",
    "reply": "LORA_REPLY_REPO",
    "feed": "LORA_FEED_REPO",
}


class LoraPipeline:
    """vLLM 기반 base model + LoRA 추론 파이프라인 (단독·멀티 겸용)."""

    def __init__(self, *, adapters: dict[str, str]) -> None:
        hf_home = os.environ.get("HF_HOME", "/app/hf-cache")
        hf_token = os.environ.get("HF_TOKEN") or None
        adapter_names = ", ".join(f"{name}={repo}" for name, repo in adapters.items())
        print(
            "[llm-worker] loading base="
            f"{_BASE_MODEL} revision={_BASE_MODEL_REVISION or 'latest'} "
            f"adapters=[{adapter_names}]"
        )

        self._llm = LLM(
            model=_BASE_MODEL,
            revision=_BASE_MODEL_REVISION,
            enable_lora=True,
            max_loras=len(adapters),  # 등록된 어댑터를 동시 상주
            max_lora_rank=64,
            dtype="float16",
            download_dir=hf_home,
            trust_remote_code=True,
            # 콜드스타트 단축: torch.compile/CUDA graph 캡처(~2분) 생략.
            # 생성 처리량이 ~10-20% 낮아지지만, 콜드스타트가 잦은 서버리스에선 이득.
            # (상시 트래픽으로 전환되면 제거해 throughput 회복 가능)
            enforce_eager=True,
        )
        self._tokenizer = self._llm.get_tokenizer()
        self._stop_token_ids = _turn_stop_token_ids(self._tokenizer)
        print(f"[llm-worker] stop_token_ids={self._stop_token_ids}")
        # LoRA int id 는 1 부터 부여(0 은 베이스로 예약).
        self._lora_requests = {}
        for idx, (name, repo) in enumerate(adapters.items(), start=1):
            local_path = snapshot_download(repo, cache_dir=hf_home, token=hf_token)
            self._lora_requests[name] = LoRARequest(name, idx, local_path)
            print(
                "[llm-worker] registered adapter="
                f"{name} repo={repo} local_path={local_path}"
            )

    def generate(
        self,
        *,
        adapter: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: int = 800,
        json_mode: bool = False,
        top_p: float = 1.0,
        top_k: int = -1,
        repetition_penalty: float = 1.0,
        guided_json: dict | None = None,
    ) -> str:
        # adapter="base"(또는 빈 값)는 LoRA 없이 base 모델로 추론한다.
        # (단일 TODO 분해기는 계획 확장 성향의 planner LoRA 대신 base 를 쓴다.)
        if adapter in ("base", "", None):
            lora_request = None
        else:
            lora_request = self._lora_requests.get(adapter)
            if lora_request is None:
                raise ValueError(
                    f"알 수 없는 adapter: {adapter!r} "
                    f"(서빙 어댑터: {sorted(self._lora_requests)} + 'base')"
                )
        prompt: str = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        from vllm.sampling_params import GuidedDecodingParams

        if guided_json is not None:
            # ponytail: backend 미지정 → vLLM 'auto'(xgrammar 등)가 JSON 스키마 강제.
            # 신버전 vLLM 은 request-level backend 선택을 막아 backend="outlines" 가 ValueError.
            # outlines 가 다시 필요하면 엔진 init 에서 --guided-decoding-backend 로 지정할 것.
            guided_decoding = GuidedDecodingParams(json=guided_json)
        elif json_mode:
            guided_decoding = GuidedDecodingParams(json_object=True)
        else:
            guided_decoding = None

        params = SamplingParams(
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            stop_token_ids=self._stop_token_ids,
            **({"guided_decoding": guided_decoding} if guided_decoding is not None else {}),
        )
        outputs = self._llm.generate([prompt], params, lora_request=lora_request)
        return outputs[0].outputs[0].text


_pipeline: LoraPipeline | None = None


def get_pipeline() -> LoraPipeline:
    """워커 프로세스에서 파이프라인을 한 번만 로드(지연).

    환경변수가 설정된 어댑터만 등록한다(단독 엔드포인트는 1개, 합본은 2개).
    """
    global _pipeline
    if _pipeline is None:
        adapters = {
            name: repo
            for name, env_key in _ADAPTER_ENV.items()
            if (repo := os.environ.get(env_key, "").strip())
        }
        if not adapters:
            raise RuntimeError(
                f"LoRA repo 환경변수가 최소 1개 필요합니다: "
                f"{', '.join(_ADAPTER_ENV.values())}"
            )
        _pipeline = LoraPipeline(adapters=adapters)
    return _pipeline
