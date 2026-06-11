from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.state import ParsedGoal, PlanDay

_MAX_SUMMARY_CHARS = 1500


async def plan_generator_node(
    state: MultiTurnGraphState, config: RunnableConfig
) -> dict[str, Any]:
    ports = get_ports(config)
    llm = ports.llm
    parsed_goal: ParsedGoal = state.get("parsed_goal") or {}
    today = state["today"]

    goal_tag = await llm.generate_goal_tag(
        parsed_goal=parsed_goal,
        history=state.get("history", []),
    )
    parsed_goal = {**parsed_goal, "goal_tag": goal_tag}
    summary_text, plan = await llm.generate_plan(parsed_goal=parsed_goal, today=today)
    if len(summary_text) > _MAX_SUMMARY_CHARS:
        summary_text, plan = await llm.generate_plan(parsed_goal=parsed_goal, today=today)
    summary_text = _truncate_summary(summary_text)
    tagged_plan = _prepare_plan_days(plan, parsed_goal=parsed_goal, today=today)

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
        "profile_memory_patch": parsed_goal.get("profile_memory_patch"),
    }


def _truncate_summary(value: str) -> str:
    if len(value) <= _MAX_SUMMARY_CHARS:
        return value
    clipped = value[:_MAX_SUMMARY_CHARS]
    last_period = max(clipped.rfind("."), clipped.rfind("。"), clipped.rfind("\n"))
    if last_period > 0:
        return clipped[: last_period + 1].strip()
    return clipped.strip()


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
