"""LLM-Modulo critic 노드 — 생성된 plan 의 soft 품질을 비평하고, major 면 재생성.

하드 제약(마감 등)은 `plan_generator` 가 이미 코드로 처리한다. critic 은 논리·부하·
순서·페이싱 같은 soft 품질만 본다. 공식 LangGraph reflection 패턴(조건부 엣지 + state
카운터)을 따른다 — 루프는 `plan_generator`/`critic` 에만 갇히고 `follow_up`(interrupt)
으로 되돌아가지 않는다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.planner.state import PlannerGraphState
from agents.todo_creation.state import ParsedGoal, PlanDay

_MAX_CRITIQUE_RETRIES = 1
# ponytail: 하루 difficulty 합 상한(task당 1~3점). minutes 환산은 신호가 필요해지면.
_DAILY_DIFFICULTY_CAP = 5

# ponytail: planner LoRA 가 비-시험 목표에 시험 task 를 흘리는 과적합 결함의 결정적 탐지.
# 진짜 해결은 SFT(스펙 Phase 5)지만, 그 전까지 최악 증상(목표 무관 시험 task)은 코드로
# 잡아 1회 재생성을 강제한다. 업그레이드 경로 = judge/critic SFT 로 LLM 이 직접 잡게.
_EXAM_LEAK_KEYWORDS = (
    "필기", "실기", "기출", "모의고사", "시험 응시", "시험응시",
    "자격증", "정처기", "정보처리기사", "과목 범위", "과목범위",
)


def _detect_overload(plan: list[PlanDay], cap: int = _DAILY_DIFFICULTY_CAP) -> list[str]:
    """하루 Σdifficulty 가 상한을 넘는 날의 ISO 날짜를 결정적으로 계산한다(critic 힌트)."""
    overloaded: list[str] = []
    for day in plan:
        load = sum(getattr(task, "difficulty", 1) for task in day.get("tasks", []))
        day_date = day.get("date")
        if load > cap and isinstance(day_date, date):
            overloaded.append(day_date.isoformat())
    return overloaded


def _detect_exam_contamination(
    plan: list[PlanDay], parsed_goal: ParsedGoal
) -> list[str]:
    """비-시험 목표 plan 에 섞인 시험/자격증 task 제목을 결정적으로 찾아낸다.

    plan_kind 이 exam 이면(시험이 정당한 목표) 빈 리스트를 돌려준다.
    """
    if parsed_goal.get("plan_kind") == "exam":
        return []
    leaked: list[str] = []
    for day in plan:
        for task in day.get("tasks", []):
            title = str(getattr(task, "title", ""))
            if any(keyword in title for keyword in _EXAM_LEAK_KEYWORDS):
                leaked.append(title)
    return leaked


def _build_revision_request(issues: list[dict[str, Any]]) -> str:
    majors = [i for i in issues if i.get("severity") == "major"]
    lines = [
        f"- {i.get('detail', '')} → {i.get('suggested_fix', '')}".strip()
        for i in majors
    ]
    return "이전 계획의 다음 문제를 고쳐 다시 분배해줘:\n" + "\n".join(lines)


async def critic_node(
    state: PlannerGraphState, config: RunnableConfig
) -> dict[str, Any]:
    parsed_goal: ParsedGoal = state.get("parsed_goal") or {}
    plan = state.get("plan") or []
    retries = state.get("critique_retries", 0)

    # routine 은 코드 전개(설계서 §3.4)라 soft 비평 대상이 아니다. 빈 plan 도 건너뛴다.
    if not plan or parsed_goal.get("plan_kind") == "routine":
        return {"needs_revision": False}

    overloaded = _detect_overload(plan)
    verdict = await get_ports(config).llm.critique_plan(
        parsed_goal=parsed_goal,
        plan=plan,
        today=state["today"],
        overloaded_days=overloaded,
    )
    issues = list(verdict.get("issues") or [])

    # LoRA 과적합 안전망: LLM critic 이 놓쳐도 목표 무관 시험 task 누수는 코드가 major 로
    # 끌어올려 재생성을 강제한다(결함: lifestyle→시험 붕괴, 메모리 planner-live-nonexam-failures).
    leaked = _detect_exam_contamination(plan, parsed_goal)
    if leaked:
        issues.append(
            {
                "day": None,
                "category": "coherence",
                "severity": "major",
                "detail": f"목표와 무관한 시험/자격증 task 가 섞임: {', '.join(leaked[:5])}",
                "suggested_fix": "시험/자격증 관련 task 를 모두 제거하고 입력 목표에 직접 맞는 일로 다시 분배해줘.",
            }
        )

    has_major = any(issue.get("severity") == "major" for issue in issues)

    if has_major and retries < _MAX_CRITIQUE_RETRIES:
        # 검증된 수정 채널: parsed_goal 에 revision_request+previous_plan 을 실어
        # plan_generator 로 backprompt(planner.py 의 사용자 수정 경로와 동일).
        revised_goal = {
            **parsed_goal,
            "revision_request": _build_revision_request(issues),
            "previous_plan": plan,
        }
        return {
            "parsed_goal": revised_goal,
            "critique_retries": retries + 1,
            "needs_revision": True,
        }
    return {"needs_revision": False}


def route_after_critic(state: PlannerGraphState) -> str:
    """needs_revision 일 때만 재생성으로, 아니면 종료(공식 조건부 엣지 패턴)."""
    return "plan_generator" if state.get("needs_revision") else END
