"""멀티턴 대화 → 단일 호출 구조화 검증 (수동 점검용).

학습된 LoRA 어댑터에 **대화(messages)** 를 넣고 한 번 생성시켜, 출력이
추론 파서 `plan_schemas.parse_plan` 로 파싱되는 구조화 플랜(GenerateResult 미러)
인지 사람이 눈으로 확인하기 위한 스크립트다. postcheck 가 valid 세트로 자동
지표를 내는 것과 달리, 여기서는 실제 대화 시나리오를 넣어 출력을 본다.

중요(분포 주의):
- SFT 학습 데이터는 **단일 user 턴(system 없음) → 플랜 JSON** 구조다.
  멀티턴 history 를 통째로 넣고 JSON 을 기대하는 건 분포 밖(OOD)일 수 있으므로,
  단일턴 baseline 과 멀티턴 시나리오를 함께 넣어 일반화 여부를 비교한다.
- 학습과 동일하게 **system 메시지를 넣지 않는다**(넣으면 train/inference skew).

실행(RunPod GPU, 학습 직후):
    python -m sft_pipeline.train.chat_infer \
        --adapter outputs/qwen7b-planner-lora

    # 직접 만든 대화로 검증(jsonl, 줄마다 {"name":..., "messages":[...]}):
    python -m sft_pipeline.train.chat_infer \
        --adapter outputs/qwen7b-planner-lora \
        --conversations my_dialogs.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sft_pipeline.build.plan_schemas import parse_plan
from sft_pipeline.train.postcheck import ends_with_eos
from sft_pipeline.train.train_lora import MAX_SEQ_LEN

# system 없는 대화만 사용한다(학습 포맷과 동일). 마지막 user 턴이 계획 요청이다.
DEFAULT_CONVERSATIONS: list[dict] = [
    {
        "name": "단일턴·시험(baseline, in-distribution)",
        "messages": [
            {
                "role": "user",
                "content": (
                    "다음 조건에 맞는 단기 시험 준비 계획을 세워줘. "
                    "시험: 정보처리기사_필기 / 남은 기간: D-7 / 하루 가용: 하루 4시간 / "
                    "시작 수준: 비전공 노베이스 / 목표: 과목당 60점 합격 / 특이사항: 직장 병행"
                ),
            },
        ],
    },
    {
        "name": "단일턴·일상(baseline, in-distribution)",
        "messages": [
            {
                "role": "user",
                "content": "'옷장 정리' 할 일을 계획하고 싶어. 언제 하는 게 좋을까? (기준일: 2026-06-07)",
            },
        ],
    },
    {
        "name": "멀티턴·일상(OOD 일반화 확인)",
        "messages": [
            {"role": "user", "content": "요즘 집이 너무 어수선해서 정리를 좀 하고 싶어."},
            {"role": "assistant", "content": "좋아요. 어떤 공간부터 손대고 싶으세요?"},
            {"role": "user", "content": "옷장이랑 책상 위주로. 주말에 몰아서 하긴 좀 부담돼."},
            {"role": "assistant", "content": "그럼 며칠에 나눠서 하는 게 낫겠네요. 기준일은 언제로 볼까요?"},
            {"role": "user", "content": "오늘이 2026-06-07이야. 이걸로 계획 세워줘."},
        ],
    },
    {
        "name": "멀티턴·시험(정보 보완 후 요청, OOD 일반화 확인)",
        "messages": [
            {"role": "user", "content": "토익 점수를 올리고 싶어."},
            {"role": "assistant", "content": "목표 점수와 시험까지 남은 기간이 어떻게 되세요?"},
            {"role": "user", "content": "850 목표고 3주 남았어. 하루 2시간 정도 낼 수 있어."},
            {"role": "assistant", "content": "현재 점수대는 어느 정도인가요?"},
            {
                "role": "user",
                "content": "700 초반이야. 기준일 2026-06-07로 단기 계획 세워줘.",
            },
        ],
    },
]


def load_conversations(path: Path) -> list[dict]:
    """jsonl 에서 대화 시나리오를 읽는다(줄마다 {"name", "messages"})."""
    convs: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        obj = json.loads(line)
        messages = obj.get("messages")
        if not messages:
            raise ValueError(f"{path}:{i + 1} 'messages' 가 없습니다")
        convs.append({"name": obj.get("name") or f"conv-{i + 1}", "messages": messages})
    return convs


def _print_conversation(messages: list[dict]) -> None:
    print("  [대화]")
    for m in messages:
        content = str(m.get("content") or "").replace("\n", " ")
        print(f"    {m.get('role')}: {content[:120]}")


def _print_plan(raw: str) -> bool:
    """생성물을 파싱해 사람이 보기 좋게 출력. 파싱 성공 여부 반환."""
    eos = ends_with_eos(raw)
    try:
        plan = parse_plan(raw)
    except ValueError as exc:
        print(f"  [생성] EOS={'✓' if eos else '✗'}  파싱=✗")
        print(f"         오류: {str(exc)[:160]}")
        print(f"         원문: {raw.strip()[:200]!r}")
        return False

    print(f"  [생성] EOS={'✓' if eos else '✗'}  파싱=✓")
    if plan.summary_text:
        print(f"         summary_text: {plan.summary_text[:160]}")
    print(f"         todos({len(plan.todos)}):")
    for t in plan.todos:
        print(f"           - {t.title} ({t.due_date}) {t.tags}")
    print(f"         calendar_events({len(plan.calendar_events)}):")
    for t in plan.calendar_events:
        print(f"           - {t.title} ({t.due_date}) {t.tags}")
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="멀티턴 대화 → 단일 호출 구조화 검증")
    parser.add_argument("--adapter", required=True, type=Path, help="학습된 LoRA 어댑터 경로")
    parser.add_argument(
        "--conversations",
        type=Path,
        default=None,
        help="대화 jsonl(줄마다 {name, messages}). 미지정 시 내장 시나리오 사용.",
    )
    parser.add_argument("--max-new-tokens", dest="max_new_tokens", type=int, default=1024)
    args = parser.parse_args(argv)

    conversations = (
        load_conversations(args.conversations) if args.conversations else DEFAULT_CONVERSATIONS
    )

    # 무거운 의존성은 함수 안에서 import(GPU 없는 환경 보호).
    from unsloth import FastLanguageModel

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(args.adapter), max_seq_length=MAX_SEQ_LEN, dtype=None, load_in_4bit=True
    )
    FastLanguageModel.for_inference(model)

    ok = 0
    for conv in conversations:
        messages = conv["messages"]
        inputs = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
        ).to(model.device)
        # do_sample=False(greedy): 같은 어댑터·대화엔 같은 결과(재현성).
        gen = model.generate(
            input_ids=inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
            use_cache=True,
        )
        raw = tokenizer.decode(gen[0][inputs.shape[1]:], skip_special_tokens=False)

        print(f"\n=== {conv['name']} (turns={len(messages)}) ===")
        _print_conversation(messages)
        if _print_plan(raw):
            ok += 1

    n = len(conversations)
    print(f"\n[chat_infer] 파싱 성공 {ok}/{n} ({(ok / n if n else 0):.0%})")


if __name__ == "__main__":
    main()
