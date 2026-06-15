"""enrichment 노드 smoke test.

실제 Tavily API 키 없이 mock enrichment 로 전체 멀티턴 플로우를 확인한다.
아래 세 시나리오를 실행한다:

  1. 정처기 시험 언급 + enrichment 활성 → 날짜 포함 follow_up 질문
  2. 정처기 시험 언급 + enrichment 비활성 → 일반 follow_up 질문
  3. 일반 목표("운동 계획") → enrichment 무관, 플랜 생성

실행:
    uv run python scripts/smoke_enrichment.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import date, datetime

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from agents.todo_creation.planner.pipeline import PlannerPorts, run
from agents.todo_creation.schemas import FollowUpResult, CandidatesResult, PlannerInput


class _FakeLLM:
    async def judge_sufficiency(self, *, history, message, today, **kw):
        from agents.todo_creation.state import ParsedGoal

        goal: ParsedGoal = {
            "goal_text": message,
            "deadline": None,
            "daily_capacity_minutes": None,
        }
        if any(w in message for w in ("시험", "정처기", "토익")):
            return False, ["scope"], goal
        return True, [], goal

    async def generate_follow_up_question(
        self, *, missing_aspects, history, enrichment_context=None
    ):
        if enrichment_context:
            keyword = enrichment_context.get("keyword", "시험")
            answer = enrichment_context.get("answer") or ""
            snippets = enrichment_context.get("snippets", [])
            hint = answer or (snippets[0][:80] if snippets else "")
            return f"[enrichment 활성] {keyword}: {hint[:80]}\n필기인가요, 실기인가요?"
        return "어떤 시험인지 알려줄 수 있어? 필기야, 실기야?"

    async def generate_plan(self, *, parsed_goal, today):
        return "플랜 생성 완료", []

    async def generate_goal_tag(self, *, parsed_goal, history):
        return (parsed_goal.get("goal_text") or "목표")[:20]

    async def tag_plan(self, *, plan, parsed_goal):
        return plan


@dataclass
class _FakeEnrichment:
    async def lookup(self, *, keyword: str, today: date) -> dict | None:
        if "정보처리기사" in keyword:
            return {
                "keyword": keyword,
                "year": today.year,
                "answer": f"{today.year}년 정보처리기사 2회 필기: 7월 5일, 실기: 8월 16일",
                "snippets": [
                    f"{today.year}년 정보처리기사 2회 필기시험: {today.year}-07-05",
                    f"{today.year}년 정보처리기사 2회 실기시험: {today.year}-08-16",
                ],
            }
        return None


async def _scenario(label: str, message: str, *, with_enrichment: bool) -> None:
    print(f"\n{'='*60}")
    print(f"시나리오: {label}")
    print(f"입력: '{message}'")
    print(f"enrichment: {'활성' if with_enrichment else '비활성'}")
    print("-" * 60)

    ports = PlannerPorts(
        llm=_FakeLLM(),
        enrichment=_FakeEnrichment() if with_enrichment else None,
    )
    inp = PlannerInput(
        user_id="smoke_user",
        message=message,
        today=date(2026, 6, 10),
    )
    result = await run(inp, ports=ports, now=datetime(2026, 6, 10, 10, 0, 0))

    if isinstance(result, FollowUpResult):
        print(f"[follow_up 질문]")
        print(f"  → {result.question}")
        print(f"  missing: {result.missing_aspects}")
    elif isinstance(result, CandidatesResult):
        print(f"[플랜 생성] todos={len(result.todos)}, events={len(result.calendar_events)}")
    else:
        print(f"[결과] {result}")


async def main() -> None:
    await _scenario(
        "정처기 시험 언급 (enrichment 활성)",
        "나 7일 뒤에 정처기 시험 있어",
        with_enrichment=True,
    )
    await _scenario(
        "정처기 시험 언급 (enrichment 비활성)",
        "나 7일 뒤에 정처기 시험 있어",
        with_enrichment=False,
    )
    await _scenario(
        "일반 목표 (enrichment 무관)",
        "운동 계획 짜줘",
        with_enrichment=True,
    )
    print(f"\n{'='*60}\nsmoke test 완료")


if __name__ == "__main__":
    asyncio.run(main())
