"""SFT 플래너 LoRA × todo_creation multi_turn 에이전트 — 대화형 실사용 점검 CLI.

vLLM 등 OpenAI 호환 엔드포인트로 서빙된 SFT LoRA(qwen7b-planner-lora)를
`SftQwenLLM` 어댑터로 기존 멀티턴 파이프라인에 꽂아, 터미널에서
되묻기(follow-up) → 플랜 생성 → 수정 요청 흐름을 직접 확인한다.

서빙 예(RunPod GPU):
    vllm serve Qwen/Qwen2.5-7B-Instruct \
        --enable-lora --lora-modules qwen7b-planner-lora=outputs/qwen7b-planner-lora

실행:
    uv run python scripts/chat_todo_sft.py --base-url http://<host>:8000/v1

명령: /state(스레드 상태) /reset(새 대화) /quit(종료)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime

from pydantic import ValidationError

from adapters.todo_creation.sft_qwen_llm import DEFAULT_SFT_MODEL, SftQwenLLM
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.multi_turn.pipeline import (
    MultiTurnPorts,
    get_debug_state,
    run,
)
from agents.todo_creation.schemas import (
    FollowUpResult,
    GenerateResult,
    MultiGenerateInput,
    OutOfScopeResult,
    TurnResult,
)


def _print_result(result: TurnResult) -> None:
    if isinstance(result, FollowUpResult):
        print(f"\n몽글이(되묻기)> {result.question}")
        if result.missing_aspects:
            print(f"  (부족한 정보: {', '.join(result.missing_aspects)})")
    elif isinstance(result, OutOfScopeResult):
        print(f"\n몽글이(범위 밖)> {result.message}")
    elif isinstance(result, GenerateResult):
        print("\n몽글이(플랜)>")
        if result.summary_text:
            print(f"  요약: {result.summary_text}")
        print(f"  todos({len(result.todos)}):")
        for t in result.todos:
            print(f"    - {t.title} ({t.due_date}) {t.tags}")
        print(f"  calendar_events({len(result.calendar_events)}):")
        for t in result.calendar_events:
            print(f"    - {t.title} ({t.due_date}) {t.tags}")
        print("  (이대로 좋으면 '확정', 바꾸려면 수정 요청을 입력하세요)")


async def chat_loop(*, ports: MultiTurnPorts, user_id: str, today: date) -> None:
    thread_id: str | None = None
    print(f"[chat] today={today.isoformat()} user={user_id} — 목표를 입력하세요.")

    while True:
        try:
            message = input("\n나> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not message:
            continue
        if message in {"/quit", "/q", "/exit"}:
            break
        if message == "/reset":
            thread_id = None
            print("[chat] 새 대화를 시작합니다.")
            continue
        if message == "/state":
            if thread_id is None:
                print("[chat] 아직 시작된 대화가 없습니다.")
            else:
                state = get_debug_state(thread_id=thread_id, ports=ports)
                for key, value in state.items():
                    print(f"  {key}: {value}")
            continue

        try:
            generate_input = MultiGenerateInput(
                user_id=user_id, message=message, today=today, thread_id=thread_id
            )
        except ValidationError as err:
            print(f"[chat] 입력 오류: {err.errors()[0].get('msg')}")
            continue

        try:
            result = await run(generate_input, ports=ports, now=datetime.now())
        except LLMFailedError as err:
            print(f"[chat] LLM 호출 실패: {err}")
            continue
        except LLMOutputError as err:
            print(f"[chat] LLM 출력 파싱 실패: {err}")
            continue

        thread_id = result.thread_id
        _print_result(result)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SFT 플래너 멀티턴 실사용 점검 CLI")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SFT_BASE_URL", "http://localhost:8000/v1"),
        help="OpenAI 호환 엔드포인트 (env: SFT_BASE_URL)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("SFT_MODEL", DEFAULT_SFT_MODEL),
        help="서빙된 모델/LoRA 이름 (env: SFT_MODEL)",
    )
    parser.add_argument("--user", default="local-dev", help="user_id")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="기준일 YYYY-MM-DD (미지정 시 오늘)",
    )
    args = parser.parse_args(argv)

    ports = MultiTurnPorts(llm=SftQwenLLM(base_url=args.base_url, model=args.model))
    today = args.today or date.today()

    try:
        asyncio.run(chat_loop(ports=ports, user_id=args.user, today=today))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
