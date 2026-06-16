"""Qwen2.5-7B-Instruct + LoRA 추론 파이프라인 (RunPod Serverless 워커용).

두 LLM 엔드포인트(플래너·빌리지)가 동일한 Docker 이미지를 공유한다.
LORA_REPO_ID 환경변수로 로드할 LoRA 를 구분한다.
"""
from __future__ import annotations

import os
from typing import Any

from huggingface_hub import snapshot_download
from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest

_BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"


class QwenLoraPipeline:
    """vLLM 기반 Qwen2.5-7B + LoRA 추론 파이프라인."""

    def __init__(self, *, lora_repo_id: str) -> None:
        hf_home = os.environ.get("HF_HOME", "/app/hf-cache")
        hf_token = os.environ.get("HF_TOKEN") or None

        lora_path = snapshot_download(
            lora_repo_id, cache_dir=hf_home, token=hf_token
        )

        self._llm = LLM(
            model=_BASE_MODEL,
            enable_lora=True,
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
        self._lora_request = LoRARequest("lora", 1, lora_path)

    def generate(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: int = 800,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        prompt: str = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        sampling_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # 후보2: 디코딩 단계 JSON 구조 강제. CJK pattern 없는 스키마만 받는다
        # (pattern 은 byte-level 백엔드에서 한국어를 깨뜨림 — PoC 결과).
        if json_schema is not None:
            from vllm.sampling_params import StructuredOutputsParams

            sampling_kwargs["structured_outputs"] = StructuredOutputsParams(
                json=json_schema
            )
        params = SamplingParams(**sampling_kwargs)
        outputs = self._llm.generate(
            [prompt], params, lora_request=self._lora_request
        )
        return outputs[0].outputs[0].text


_pipeline: QwenLoraPipeline | None = None


def get_pipeline() -> QwenLoraPipeline:
    global _pipeline
    if _pipeline is None:
        lora_repo_id = os.environ.get("LORA_REPO_ID", "").strip()
        if not lora_repo_id:
            raise RuntimeError("LORA_REPO_ID 환경변수가 필요합니다")
        _pipeline = QwenLoraPipeline(lora_repo_id=lora_repo_id)
    return _pipeline
