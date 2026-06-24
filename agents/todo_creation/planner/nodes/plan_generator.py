from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.planner.allocator import expand_routine
from agents.todo_creation.planner.state import PlannerGraphState
from agents.todo_creation.state import ParsedGoal, PlanDay

_MAX_SUMMARY_CHARS = 1500
_DEFAULT_ROUTINE_HORIZON = 28
# 재생성(critic backprompt) 은 1차와 달라져야 의미가 있다 → Qwen 기본 temp(0.7)로 샘플링
# 다양성을 준다. 1차 생성은 낮은 기본 temp(어댑터 0.1)로 둔다(레버①).
_REGEN_TEMPERATURE = 0.7


async def plan_generator_node(
    state: PlannerGraphState, config: RunnableConfig
) -> dict[str, Any]:
    ports = get_ports(config)
    llm = ports.llm
    parsed_goal: ParsedGoal = state.get("parsed_goal") or {}
    today = state["today"]

    # routine: cadence 를 horizon 으로 결정적 전개(LLM 생략, 설계서 §3.4).
    if parsed_goal.get("plan_kind") == "routine":
        return _routine_plan(parsed_goal, today=today)

    goal_tag = await llm.generate_goal_tag(
        parsed_goal=parsed_goal,
        history=state.get("history", []),
    )
    parsed_goal = {**parsed_goal, "goal_tag": goal_tag}
    regen_temp = (
        _REGEN_TEMPERATURE if state.get("critique_retries", 0) >= 1 else None
    )
    summary_text, plan = await llm.generate_plan(
        parsed_goal=parsed_goal, today=today, temperature=regen_temp
    )
    if len(summary_text) > _MAX_SUMMARY_CHARS:
        summary_text, plan = await llm.generate_plan(
            parsed_goal=parsed_goal, today=today, temperature=regen_temp
        )
    summary_text = _truncate_summary(summary_text)
    tagged_plan = _prepare_plan_days(plan, parsed_goal=parsed_goal, today=today)
    tagged_plan = _enforce_deadline(tagged_plan, today=today, deadline=parsed_goal.get("deadline"))

    todos = []
    calendar_events = []
    for day in tagged_plan:
        for task in day.get("tasks", []):
            if task.due_date == today:
                todos.append(task)
            else:
                calendar_events.append(task)

    return {
        "summary_text": summary_text,
        "plan": tagged_plan,
        "todos": todos,
        "calendar_events": calendar_events,
        "personalization_patch": parsed_goal.get("personalization_patch"),
        # generate_plan 이 실은 rationale(객관 근거)·goal_tag 를 state 로 전파해 critic 이 본다.
        "parsed_goal": parsed_goal,
    }


def _routine_plan(parsed_goal: ParsedGoal, *, today: date) -> dict[str, Any]:
    """routine plan_kind 을 코드로 전개한다 — cadence 를 horizon 내 날짜로 펼침.

    LLM 을 전혀 호출하지 않는다(설계서 §3.4: 슬롯이 곧 내용). judge 가 채운
    goal_tag 로 일괄 태깅하고, 마감일 이후는 expand_routine 이 clamp 한다.
    """
    slots = parsed_goal.get("slots") or {}
    activity = str(slots.get("activity") or parsed_goal.get("goal_text") or "루틴")
    cadence = str(slots.get("cadence") or "")
    horizon = _routine_horizon(slots.get("horizon"))
    goal_tag = _normalize_goal_tag(parsed_goal.get("goal_tag"))
    deadline = parsed_goal.get("deadline")

    events = [
        event.model_copy(update={"tags": [goal_tag]})
        for event in expand_routine(
            activity, cadence, today=today, horizon_days=horizon, deadline=deadline
        )
    ]
    todos = [e for e in events if e.due_date == today]
    calendar_events = [e for e in events if e.due_date != today]
    plan: list[PlanDay] = [{"date": e.due_date, "tasks": [e]} for e in events]
    summary_text = _truncate_summary(
        f"'{activity}' 루틴을 {cadence or '정해진 주기'} 기준으로 "
        f"다음 {horizon}일 동안 잡아뒀어요."
    )
    return {
        "summary_text": summary_text,
        "plan": plan,
        "todos": todos,
        "calendar_events": calendar_events,
        "personalization_patch": parsed_goal.get("personalization_patch"),
    }


def _routine_horizon(value: Any) -> int:
    """horizon 슬롯이 정수 일수면 사용, 아니면 기본 28일.

    ponytail: 자연어 기간("한 달")은 v1 비범위 — 기본 28일로 충분(설계서 D5).
    """
    if isinstance(value, int) and value > 0:
        return value
    return _DEFAULT_ROUTINE_HORIZON


def _truncate_summary(value: str) -> str:
    if len(value) <= _MAX_SUMMARY_CHARS:
        return value
    clipped = value[:_MAX_SUMMARY_CHARS]
    last_period = max(clipped.rfind("."), clipped.rfind("。"), clipped.rfind("\n"))
    if last_period > 0:
        return clipped[: last_period + 1].strip()
    return clipped.strip()


def _enforce_deadline(
    plan: list[PlanDay], *, today: date, deadline: date | None
) -> list[PlanDay]:
    """deadline 기준으로 plan 의 날짜를 정리한다(코드가 날짜를 소유).

    - deadline 없음 → 원본 유지(짧은 horizon, 기존 거동 보존).
    - 모델이 마감 전에 끝냄(truncation 버그) → today~deadline 전체로 재분배해 마지막날=deadline 보장.
    - 모델이 마감까지/이후로 만듦 → 마감 이후만 잘라낸다(기존 P1 거동: 회고 등 군더더기 차단).
    """
    if deadline is None:
        return plan
    dates = [day["date"] for day in plan if isinstance(day.get("date"), date)]
    if dates and max(dates) < deadline:
        return _distribute_to_deadline(plan, today=today, deadline=deadline)
    return [day for day in plan if day["date"] <= deadline]


def _distribute_to_deadline(
    plan: list[PlanDay], *, today: date, deadline: date
) -> list[PlanDay]:
    """마일스톤 PlanDay 들을 today~deadline 전체에 고르게 재배치한다(truncation 차단).

    모델이 정한 날짜는 무시하고 '순서'만 쓴다. 첫날=today, 마지막날=deadline 을 보장한다.
    """
    days = [day for day in plan if day.get("tasks")]
    if not days or deadline <= today:
        return [day for day in plan if day["date"] <= deadline]

    span = (deadline - today).days
    # 캘린더 슬롯보다 많은 날을 만들 수 없다(겹침 방지). 초과 마일스톤은 버린다.
    if len(days) - 1 > span:
        days = days[: span + 1]
    count = len(days)

    redated: list[PlanDay] = []
    for index, day in enumerate(days):
        # count==1 → today(지금 시작). count>=2 → 첫날=today, 마지막날=deadline 으로 균등 배치.
        offset = 0 if count == 1 else round(index * span / (count - 1))
        current = today + timedelta(days=offset)
        tasks = [task.model_copy(update={"due_date": current}) for task in day["tasks"]]
        redated.append({**day, "date": current, "tasks": tasks})
    return redated


def _prepare_plan_days(
    plan: list[PlanDay], *, parsed_goal: ParsedGoal, today: date
) -> list[PlanDay]:
    """모델 출력의 날짜를 하루 단위로 정리하고 동일 goal_tag 를 붙인다."""

    if not plan:
        return []

    raw_dates: list[date] = []
    for day in plan:
        planned_date = day.get("date")
        if isinstance(planned_date, date):
            raw_dates.append(planned_date)
    should_spread = len(set(raw_dates)) <= 1
    start_date = max(today, raw_dates[0]) if raw_dates else today
    goal_tag = _normalize_goal_tag(parsed_goal.get("goal_tag") or parsed_goal.get("goal_text"))

    prepared: list[PlanDay] = []
    previous_date: date | None = None

    for index, day in enumerate(plan):
        planned_date = day.get("date")
        if isinstance(planned_date, date) and not should_spread:
            current_date = planned_date
        elif index == 0:
            current_date = start_date
        else:
            current_date = (previous_date or start_date) + timedelta(days=1)

        tasks = [
            task.model_copy(update={"due_date": current_date, "tags": [goal_tag]})
            for task in day.get("tasks", [])
        ]
        prepared.append({**day, "date": current_date, "tasks": tasks})
        previous_date = current_date

    return prepared


def _normalize_goal_tag(value: Any) -> str:
    tag = str(value or "목표").strip()

    # 태그 의미 생성은 LLM 에 맡기고, 여기서는 DB 저장 가능한 짧은 문자열로만 정리한다.
    tag = re.sub(r"^(나|저|내|제)+", "", tag)
    tag = re.sub(r"(으로|로|에서|에게|한테|부터|까지|하고|이랑|랑|을|를|은|는|이|가|에)$", "", tag)
    tag = re.sub(r"[\s/\\,.?!~]+", "", tag)
    return (tag or "목표")[:20]
