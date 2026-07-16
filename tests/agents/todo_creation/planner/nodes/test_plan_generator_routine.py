"""routine plan_kind: 코드가 cadence 를 horizon 으로 전개하고 LLM 을 생략한다.

설계서 §3.4 "routine ≈ 0(슬롯=내용, LLM 생략), 코드가 cadence 펼침" (Phase 2A 배선).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from agents.todo_creation.planner.nodes.plan_generator import plan_generator_node
from agents.todo_creation.state import ParsedGoal

_TODAY = date(2026, 5, 27)


@dataclass
class _BoomLLM:
    """routine 경로는 어떤 LLM 도 호출하면 안 된다(결정적 전개)."""

    async def generate_plan(self, **_):  # noqa: ANN003
        raise AssertionError("routine 은 generate_plan 을 호출하면 안 된다")

    async def generate_goal_tag(self, **_):  # noqa: ANN003
        raise AssertionError("routine 은 generate_goal_tag 를 호출하면 안 된다")

    async def judge_sufficiency(self, **_): ...
    async def generate_follow_up_question(self, **_): ...
    async def split_tasks(self, **_): ...


@dataclass
class _Ports:
    llm: _BoomLLM


def _config() -> dict:
    return {"configurable": {"ports": _Ports(llm=_BoomLLM())}}


def _state(parsed_goal: ParsedGoal) -> dict:
    return {"today": _TODAY, "parsed_goal": parsed_goal}


async def test_routine_expands_cadence_without_llm() -> None:
    parsed_goal: ParsedGoal = {
        "plan_kind": "routine",
        "slots": {"activity": "독서", "cadence": "월수금"},
        "goal_tag": "독서루틴",
        "deadline": None,
    }

    result = await plan_generator_node(_state(parsed_goal), _config())

    events = (result["calendar_events"] or []) + (result["todos"] or [])
    assert events, "routine 은 horizon 내 이벤트를 만들어야 한다"
    # 월수금 = weekday 0,2,4 만
    assert all(e.due_date.weekday() in {0, 2, 4} for e in events)
    # judge 가 채운 goal_tag 로 일괄 태깅
    assert all(e.tags == ["독서루틴"] for e in events)
    # revision 감지를 위해 plan 채움
    assert result["plan"]


async def test_routine_clamps_to_deadline() -> None:
    parsed_goal: ParsedGoal = {
        "plan_kind": "routine",
        "slots": {"activity": "스트레칭", "cadence": "주7회"},  # 매일 분산
        "goal_tag": "스트레칭",
        "deadline": _TODAY + timedelta(days=3),
    }

    result = await plan_generator_node(_state(parsed_goal), _config())

    events = (result["calendar_events"] or []) + (result["todos"] or [])
    assert events
    assert all(e.due_date <= _TODAY + timedelta(days=3) for e in events)
    # today..today+3 = 4일, 매일 → 4개
    assert len(events) == 4


async def test_routine_uses_structured_items_without_domain_specific_code() -> None:
    parsed_goal: ParsedGoal = {
        "plan_kind": "routine",
        "slots": {
            "activity": "러닝",
            "cadence": "월수금",
            "routine_items": ["이지런", "인터벌 러닝", "롱런"],
        },
        "goal_tag": "러닝",
        "deadline": None,
    }

    result = await plan_generator_node(_state(parsed_goal), _config())

    first_week = sorted(
        [
            event
            for event in result["todos"] + result["calendar_events"]
            if event.due_date < _TODAY + timedelta(days=7)
        ],
        key=lambda event: event.due_date,
    )
    assert [event.title for event in first_week] == [
        "인터벌 러닝",
        "롱런",
        "이지런",
    ]


async def test_routine_activity_corrupted_stringified_list_is_coerced() -> None:
    """모델이 activity 를 '["a","a"]' stringified-list 로 오염시켜도 title 이 깨지지 않는다.

    (revision 턴에서 관측된 회귀: title 이 리스트 repr 로 박혀 일정이 무너짐)
    """
    goal: ParsedGoal = {
        "plan_kind": "routine",
        "goal_text": "월수금 헬스 진행하기",
        "goal_tag": "헬스루틴",
        "slots": {"activity": '["월수금 헬스", "월수금 헬스"]', "cadence": "월수금"},
    }
    result = await plan_generator_node(_state(goal), _config())
    events = (result["calendar_events"] or []) + (result["todos"] or [])
    titles = [e.title for e in events]
    assert titles, "일정이 있어야 함"
    assert all(not t.startswith("[") for t in titles), f"오염된 title: {titles}"
    # 정제되어 첫 항목만 남는다
    assert all(t == "월수금 헬스" for t in titles), titles
