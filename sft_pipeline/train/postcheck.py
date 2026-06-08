"""학습 후 점검 자동화 (sft-coherence Phase 6).

학습이 끝난 LoRA 어댑터를 받아 세 가지를 자동 점검한다:
1. **EOS 끝맺음**: 생성물이 턴 종료 마커로 끝나는지(무한 생성/잘림 방지, 원칙 4).
2. **과적합 경고**: validation loss < 0.2 면 암기(과적합) 의심(Phase 6).
3. **파싱 성공률**: 생성물을 추론 파서 `plan_schemas.parse_plan` 로 파싱해 성공률 측정
   — 이게 SFT 의 진짜 목표(구조화 플랜 정합성). distractor 는 평문이라 제외하고
   task_type='plan'(시험/일상) 샘플로만 측정.

순수 함수(아래 4개)는 GPU 없이 테스트 가능하고, 실제 생성은 main 에서 unsloth 로 한다.

실행(RunPod GPU, 학습 직후):
    python -m sft_pipeline.train.postcheck \
        --valid sft_pipeline/data/generated/sft_valid.jsonl \
        --adapter outputs/qwen7b-planner-lora --n-samples 20
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sft_pipeline.build.plan_schemas import parse_plan
from sft_pipeline.train.train_lora import MAX_SEQ_LEN

# Qwen2.5 chat template 의 턴 종료/문서 종료 마커(EOS 계열).
_EOS_MARKERS = ("<|im_end|>", "<|endoftext|>")


def ends_with_eos(text: str, markers: tuple[str, ...] = _EOS_MARKERS) -> bool:
    """생성물이 EOS 계열 마커로 끝나는지(뒤 공백 무시)."""
    tail = text.rstrip()
    return any(tail.endswith(m) for m in markers)


def parse_success_rate(texts: list[str]) -> dict:
    """생성물들을 parse_plan 으로 파싱해 성공률·실패목록 반환."""
    failures: list[dict] = []
    ok = 0
    for i, text in enumerate(texts):
        try:
            parse_plan(text)
            ok += 1
        except ValueError as exc:
            failures.append({"index": i, "error": str(exc)[:120], "preview": text[:60]})
    n = len(texts)
    return {"n": n, "rate": (ok / n) if n else 0.0, "failures": failures}


def overfit_warning(eval_loss: float | None, threshold: float = 0.2) -> str | None:
    """eval_loss 가 임계 미만이면 과적합 경고 메시지, 아니면 None."""
    if eval_loss is None:
        return None
    if eval_loss < threshold:
        return (
            f"⚠️ 과적합 의심: eval_loss={eval_loss:.3f} < {threshold}. "
            "epoch를 줄이거나(예: 1) 데이터를 늘리세요."
        )
    return None


def read_eval_loss(checkpoint_dir: str | Path) -> float | None:
    """trainer_state.json 에서 마지막 eval_loss 를 읽는다. 없으면 None."""
    base = Path(checkpoint_dir)
    direct = base / "trainer_state.json"
    candidates = [direct] if direct.exists() else sorted(base.glob("**/trainer_state.json"))
    if not candidates:
        return None
    state = json.loads(candidates[-1].read_text(encoding="utf-8"))
    evals = [e["eval_loss"] for e in state.get("log_history", []) if "eval_loss" in e]
    return evals[-1] if evals else None


def _plan_prompts(valid_path: Path, limit: int) -> list[list[dict]]:
    """valid 에서 task_type='plan' 샘플만 골라 user 턴까지의 메시지를 반환(생성용)."""
    prompts: list[list[dict]] = []
    for line in valid_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sample = json.loads(line)
        if (sample.get("meta") or {}).get("task_type") != "plan":
            continue
        msgs = sample["messages"]
        # 마지막 assistant 를 떼고 user 까지만 모델에 준다.
        prompts.append([m for m in msgs if m["role"] != "assistant"])
        if len(prompts) >= limit:
            break
    return prompts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="학습 후 점검(EOS·과적합·파싱 성공률)")
    parser.add_argument("--valid", required=True, type=Path)
    parser.add_argument("--adapter", required=True, type=Path, help="학습된 LoRA 어댑터 경로")
    parser.add_argument("--n-samples", dest="n_samples", type=int, default=20)
    parser.add_argument("--max-new-tokens", dest="max_new_tokens", type=int, default=1024)
    parser.add_argument("--out", type=Path, default=None, help="리포트 JSON 저장(선택)")
    args = parser.parse_args(argv)

    # 무거운 의존성은 함수 안에서 import(GPU 없는 환경 보호).
    from unsloth import FastLanguageModel

    prompts = _plan_prompts(args.valid, args.n_samples)
    if not prompts:
        raise SystemExit(f"[postcheck] task_type='plan' 샘플이 없습니다: {args.valid}")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(args.adapter), max_seq_length=MAX_SEQ_LEN, dtype=None, load_in_4bit=True
    )
    # 저장된 어댑터의 토크나이저는 chat template 을 이미 포함 → get_chat_template 불필요.
    FastLanguageModel.for_inference(model)

    raw_outputs: list[str] = []
    clean_outputs: list[str] = []
    for msgs in prompts:
        inputs = tokenizer.apply_chat_template(
            msgs, tokenize=True, add_generation_prompt=True, return_tensors="pt"
        ).to(model.device)
        # do_sample=False(greedy): 점검 재현성 확보 — 같은 어댑터·입력엔 같은 결과.
        gen = model.generate(
            input_ids=inputs, max_new_tokens=args.max_new_tokens, do_sample=False, use_cache=True
        )
        new_tokens = gen[0][inputs.shape[1]:]
        raw_outputs.append(tokenizer.decode(new_tokens, skip_special_tokens=False))
        clean_outputs.append(tokenizer.decode(new_tokens, skip_special_tokens=True))

    eos_ok = sum(ends_with_eos(t) for t in raw_outputs)
    eos_rate = eos_ok / len(raw_outputs)
    parse = parse_success_rate(clean_outputs)
    eval_loss = read_eval_loss(args.adapter / "checkpoints")
    warn = overfit_warning(eval_loss)

    report = {
        "n_samples": len(prompts),
        "eos_rate": eos_rate,
        "parse_success_rate": parse["rate"],
        "parse_failures": parse["failures"],
        "eval_loss": eval_loss,
        "overfit_warning": warn,
    }

    print(f"[postcheck] 샘플 {report['n_samples']}건")
    print(f"[postcheck] EOS 끝맺음률      : {eos_rate:.1%}  (1.0 목표 — 미만이면 무한생성/잘림 의심)")
    print(f"[postcheck] 파싱 성공률(목표)  : {parse['rate']:.1%}  ({parse['n']}건 중)")
    print(f"[postcheck] eval_loss        : {eval_loss}")
    if warn:
        print(f"[postcheck] {warn}")
    if parse["failures"]:
        print(f"[postcheck] 파싱 실패 {len(parse['failures'])}건(앞 3개):")
        for f in parse["failures"][:3]:
            print(f"            #{f['index']} {f['error']} | {f['preview']!r}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[postcheck] 리포트 저장: {args.out}")


if __name__ == "__main__":
    main()
