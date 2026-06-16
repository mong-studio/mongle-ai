"""구조화 생성 비교 PoC 하니스 (후보 1+2: 중국어 차단 + JSON 강제).

★ 로컬(macOS) 실행 불가 — GPU + Qwen2.5-7B + LoRA 필요. RunPod/GPU 박스에서 실행.

세 변종을 동일 프롬프트셋에 돌려 production task-splitter 경로 그대로 비교한다:
  baseline       : 현재 방식(자유 생성 → 코드펜스 제거 → json.loads → 검증/재시도)
  vllm_native    : SamplingParams(structured_outputs=StructuredOutputsParams(json=schema))
                   → 내부 백엔드(xgrammar/outlines)가 logits 제약. 새 의존성 0.
  outlines_direct: outlines.from_vllm_offline(llm) + output_type=ConstrainedSplit

지표:
  json_ok  : production 이 수용할 JSON 인가(intent/tasks/due_date/title≤20). CJK 무관.
  cjk      : 한자/가나가 출력에 섞였는가(낮을수록 좋음 = 후보 1 효과).
  strict   : 제약 스키마(ConstrainedSplit, CJK 금지 포함) 완전 통과.
  ms       : 평균 생성 지연.

실행:
  cd <repo-root>
  export LORA_REPO_ID=bigmooon/qwen2.5-7b-mongle-planner-ko-lora HF_TOKEN=...
  python -m scripts.outlines_poc.run                 # 세 변종 전부(콘솔 표)
  python -m scripts.outlines_poc.run --variants vllm_native outlines_direct
  python -m scripts.outlines_poc.run --report poc_results.ipynb   # 표 포함 노트북 보고서

--report 지정 시 요약표 + 변종별 프롬프트 상세표가 담긴 .ipynb 를 생성한다
(RunPod 에서 실행 후 그 파일을 내려받아 발표자료 근거로 사용).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

# repo-root 를 path 에 올려 adapters/* 를 import (PoC 는 repo 체크아웃에서 실행).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.todo_creation._prompts import (  # noqa: E402
    TASK_SPLITTER_SYSTEM,
    task_splitter_user,
)
from scripts.outlines_poc.constrained import (  # noqa: E402
    ConstrainedSplit,
    contains_cjk,
    split_json_schema,
)
from scripts.outlines_poc.eval_prompts import EVAL_PROMPTS, TODAY  # noqa: E402

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"  # mirror: runpod_workers/llm/pipeline.py:15
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


# --- 모델 로드 (vLLM) --------------------------------------------------------
def load_llm():
    import os

    from vllm import LLM

    hf_home = os.environ.get("HF_HOME", "/app/hf-cache")
    return LLM(
        model=BASE_MODEL,
        enable_lora=True,
        max_lora_rank=64,
        dtype="float16",
        download_dir=hf_home,
        trust_remote_code=True,
        enforce_eager=True,
    )


def load_lora():
    import os

    from huggingface_hub import snapshot_download
    from vllm.lora.request import LoRARequest

    repo = os.environ.get("LORA_REPO_ID", "").strip()
    if not repo:
        print("⚠ LORA_REPO_ID 미설정 — 베이스 모델로만 측정(SFT 효과 제외)")
        return None
    path = snapshot_download(
        repo,
        cache_dir=os.environ.get("HF_HOME", "/app/hf-cache"),
        token=os.environ.get("HF_TOKEN") or None,
    )
    return LoRARequest("lora", 1, path)


def build_prompt(tokenizer, user_text: str) -> str:
    messages = [
        {"role": "system", "content": TASK_SPLITTER_SYSTEM},
        {"role": "user", "content": task_splitter_user(user_text, TODAY)},
    ]
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )


# --- 변종별 생성 함수 (raw text 반환) ---------------------------------------
def gen_baseline(llm, lora, prompt: str) -> str:
    from vllm import SamplingParams

    params = SamplingParams(temperature=0.1, max_tokens=800)
    out = llm.generate([prompt], params, lora_request=lora)
    return out[0].outputs[0].text


def gen_vllm_native(llm, lora, prompt: str) -> str:
    from vllm import SamplingParams
    from vllm.sampling_params import StructuredOutputsParams

    so = StructuredOutputsParams(json=split_json_schema())
    params = SamplingParams(temperature=0.1, max_tokens=800, structured_outputs=so)
    out = llm.generate([prompt], params, lora_request=lora)
    return out[0].outputs[0].text


def make_outlines(llm):
    import outlines

    return outlines.from_vllm_offline(llm)


def gen_outlines(model, lora, prompt: str) -> str:
    from vllm import SamplingParams

    params = SamplingParams(temperature=0.1, max_tokens=800)
    # LoRA 전달: from_vllm_offline 이 lora_request 를 노출하는지 버전 의존.
    # 우선 시도 → TypeError 면 LoRA 없이(베이스) 폴백.
    try:
        return model(
            prompt, output_type=ConstrainedSplit, sampling_params=params,
            lora_request=lora,
        )
    except TypeError:
        return model(prompt, output_type=ConstrainedSplit, sampling_params=params)


# --- 평가 -------------------------------------------------------------------
def _strip_fence(raw: str) -> str:
    m = _FENCE_RE.search(raw)
    return m.group(1).strip() if m else raw.strip()


def lenient_json_ok(raw: str) -> bool:
    """production 이 수용할 JSON 인가(CJK 무관). qwen_llm.parse_task_response 기준."""
    try:
        obj = json.loads(_strip_fence(raw))
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(obj, dict):
        return False
    tasks = obj.get("tasks", [])
    if not isinstance(tasks, list):
        return False
    for t in tasks:
        try:
            date.fromisoformat(str(t["due_date"]))
            if not 1 <= len(str(t["title"])) <= 20:
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def strict_ok(raw: str) -> bool:
    try:
        ConstrainedSplit.model_validate_json(_strip_fence(raw))
        return True
    except Exception:
        return False


# --- 메인 -------------------------------------------------------------------
GENERATORS = ("baseline", "vllm_native", "outlines_direct")


def run_variant(name, runner, prompts):
    """(요약 dict, 프롬프트별 record 리스트) 반환."""
    n = len(prompts)
    agg = {"json_ok": 0, "cjk": 0, "strict": 0, "ms": 0.0}
    records: list[dict] = []
    for prompt, expect in prompts:
        t0 = time.perf_counter()
        raw = runner(prompt)
        ms = (time.perf_counter() - t0) * 1000
        rec = {
            "prompt": prompt,
            "expect": expect,
            "json_ok": lenient_json_ok(raw),
            "cjk": contains_cjk(raw),
            "strict": strict_ok(raw),
            "ms": ms,
            "raw": raw,
        }
        records.append(rec)
        agg["ms"] += ms
        agg["json_ok"] += rec["json_ok"]
        agg["cjk"] += rec["cjk"]
        agg["strict"] += rec["strict"]
    summary = {
        "variant": name,
        "json_ok%": 100 * agg["json_ok"] / n,
        "cjk%": 100 * agg["cjk"] / n,
        "strict%": 100 * agg["strict"] / n,
        "mean_ms": agg["ms"] / n,
    }
    return summary, records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+", default=list(GENERATORS), choices=GENERATORS)
    ap.add_argument("--limit", type=int, default=0, help="앞 N개만(0=전체)")
    ap.add_argument(
        "--report",
        default="",
        help="결과 노트북(.ipynb) 출력 경로. 지정 시 표 포함 보고서 생성.",
    )
    args = ap.parse_args()

    prompts = EVAL_PROMPTS[: args.limit] if args.limit else EVAL_PROMPTS

    print(f"모델 로드: {BASE_MODEL} (+LoRA)")
    llm = load_llm()
    lora = load_lora()
    tokenizer = llm.get_tokenizer()

    # 프롬프트는 변종 무관 동일 — 한 번만 chat-template 적용.
    templated = {p: build_prompt(tokenizer, p) for p, _ in prompts}
    olm = make_outlines(llm) if "outlines_direct" in args.variants else None

    runners = {
        "baseline": lambda p: gen_baseline(llm, lora, templated[p]),
        "vllm_native": lambda p: gen_vllm_native(llm, lora, templated[p]),
        "outlines_direct": lambda p: gen_outlines(olm, lora, templated[p]),
    }

    results = {v: run_variant(v, runners[v], prompts) for v in args.variants}
    rows = [results[v][0] for v in args.variants]
    records_by_variant = {v: results[v][1] for v in args.variants}

    print(f"\n=== 결과 (n={len(prompts)}) ===")
    hdr = f"{'variant':<16}{'json_ok%':>10}{'cjk%':>8}{'strict%':>9}{'mean_ms':>10}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['variant']:<16}{r['json_ok%']:>10.1f}{r['cjk%']:>8.1f}"
            f"{r['strict%']:>9.1f}{r['mean_ms']:>10.0f}"
        )

    if args.report:
        from datetime import datetime

        from scripts.outlines_poc import report

        meta = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": BASE_MODEL,
            "lora": (getattr(lora, "lora_path", str(lora)) if lora else "(none)"),
            "n": len(prompts),
            "variants": args.variants,
        }
        report.build_report_notebook(
            meta=meta, rows=rows, records_by_variant=records_by_variant,
            out_path=args.report,
        )
        print(f"\n📓 결과 노트북 생성: {args.report}")


if __name__ == "__main__":
    main()
