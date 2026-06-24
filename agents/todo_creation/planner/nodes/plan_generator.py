from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.planner.allocator import expand_routine
from agents.todo_creation.planner.conversation_style import render_chief_voice
from agents.todo_creation.planner.state import PlannerGraphState
from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay

_MAX_SUMMARY_CHARS = 1500
_DEFAULT_ROUTINE_HORIZON = 28
_MAX_PLAN_DAYS = 30
_MAX_TASKS = 15


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
    summary_text, plan = await llm.generate_plan(parsed_goal=parsed_goal, today=today)
    if len(summary_text) > _MAX_SUMMARY_CHARS:
        summary_text, plan = await llm.generate_plan(
            parsed_goal=parsed_goal, today=today
        )
    summary_text, tagged_plan = _prepare_generated_plan(
        summary_text, plan, parsed_goal=parsed_goal, today=today
    )
    issues = await _validation_issues(
        getattr(ports, "validator", None),
        plan=tagged_plan,
        summary_text=summary_text,
        parsed_goal=parsed_goal,
        today=today,
    )
    if issues:
        corrected_goal = {
            **parsed_goal,
            "revision_request": "다음 품질 문제를 모두 고쳐 다시 생성: "
            + "; ".join(issues),
        }
        summary_text, plan = await llm.generate_plan(
            parsed_goal=corrected_goal, today=today
        )
        summary_text, tagged_plan = _prepare_generated_plan(
            summary_text, plan, parsed_goal=parsed_goal, today=today
        )
        issues = await _validation_issues(
            getattr(ports, "validator", None),
            plan=tagged_plan,
            summary_text=summary_text,
            parsed_goal=parsed_goal,
            today=today,
        )
        if issues:
            raise LLMOutputError(
                "plan quality validation failed after retry: " + "; ".join(issues)
            )

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
    ][:_MAX_TASKS]
    todos = [e for e in events if e.due_date == today]
    calendar_events = [e for e in events if e.due_date != today]
    plan: list[PlanDay] = [{"date": e.due_date, "tasks": [e]} for e in events]
    summary_text = render_chief_voice(_truncate_summary(
        f"'{activity}' 루틴을 {cadence or '정해진 주기'} 기준으로 "
        f"다음 {horizon}일 동안 잡아뒀어요."
    ))
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


def _prepare_generated_plan(
    summary_text: str,
    plan: list[PlanDay],
    *,
    parsed_goal: ParsedGoal,
    today: date,
) -> tuple[str, list[PlanDay]]:
    prepared = _prepare_plan_days(plan, parsed_goal=parsed_goal, today=today)
    scheduled = _schedule_plan_window(
        prepared,
        today=today,
        deadline=parsed_goal.get("deadline"),
    )
    summary = _append_plan_context(
        _truncate_summary(summary_text),
        parsed_goal=parsed_goal,
        today=today,
    )
    return _render_summary(summary), scheduled


def _schedule_plan_window(
    plan: list[PlanDay], *, today: date, deadline: date | None
) -> list[PlanDay]:
    window_end = today + timedelta(days=_MAX_PLAN_DAYS - 1)
    if deadline is None:
        kept: list[PlanDay] = []
        task_count = 0
        for day in plan:
            planned_date = min(max(day["date"], today), window_end)
            remaining = _MAX_TASKS - task_count
            if remaining <= 0:
                break
            tasks = [
                task.model_copy(update={"due_date": planned_date})
                for task in day.get("tasks", [])[:remaining]
            ]
            if tasks:
                kept.append({"date": planned_date, "tasks": tasks})
                task_count += len(tasks)
        return kept

    tasks = [
        task
        for day in plan
        if day["date"] <= deadline
        for task in day.get("tasks", [])
    ][:_MAX_TASKS]
    if not tasks:
        return []

    target_end = min(deadline, window_end)
    target_end = max(today, target_end)
    span = (target_end - today).days
    if len(tasks) == 1:
        dates = [target_end]
    else:
        dates = [
            today + timedelta(days=round(span * index / (len(tasks) - 1)))
            for index in range(len(tasks))
        ]

    grouped: dict[date, list[TaskCandidate]] = {}
    for task, planned_date in zip(tasks, dates, strict=True):
        grouped.setdefault(planned_date, []).append(
            task.model_copy(update={"due_date": planned_date})
        )
    return [
        {"date": planned_date, "tasks": grouped[planned_date]}
        for planned_date in sorted(grouped)
    ]


def _append_plan_context(
    summary: str, *, parsed_goal: ParsedGoal, today: date
) -> str:
    parts = [summary.strip()] if summary.strip() else []
    assumptions = parsed_goal.get("assumptions") or []
    if assumptions:
        parts.append("확인되지 않은 정보는 " + ", ".join(assumptions) + "으로 잡았어요.")
    deadline = parsed_goal.get("deadline")
    window_end = today + timedelta(days=_MAX_PLAN_DAYS - 1)
    if deadline and deadline > window_end:
        parts.append(
            f"상세 일정은 {window_end.isoformat()}까지 제공하고, "
            "그 이후에는 목표일까지 같은 흐름을 월별 단계로 이어가면 돼요."
        )
    return " ".join(parts)


def _render_summary(summary: str) -> str:
    suffix = ", 몽글."
    base = _truncate_summary(summary)
    if len(base) + len(suffix) > _MAX_SUMMARY_CHARS:
        base = base[: _MAX_SUMMARY_CHARS - len(suffix)].rstrip(" .!?~")
    return render_chief_voice(base)


async def _validation_issues(
    validator: Any,
    *,
    plan: list[PlanDay],
    summary_text: str,
    parsed_goal: ParsedGoal,
    today: date,
) -> list[str]:
    if validator is None:
        return []
    issues = _deterministic_issues(plan, parsed_goal=parsed_goal, today=today)
    validate = getattr(validator, "validate_plan", None)
    if validate is not None:
        valid, semantic_issues = await validate(
            plan=plan,
            summary_text=summary_text,
            parsed_goal=parsed_goal,
            today=today,
        )
        if not valid:
            issues.extend(semantic_issues or ["목표 관련성 또는 문장 품질 미달"])
    return list(dict.fromkeys(issues))


def _deterministic_issues(
    plan: list[PlanDay], *, parsed_goal: ParsedGoal, today: date
) -> list[str]:
    tasks = [task for day in plan for task in day.get("tasks", [])]
    if not tasks:
        return ["일정이 비어 있음"]
    if len(tasks) > _MAX_TASKS:
        return [f"일정이 {_MAX_TASKS}개를 초과함"]
    window_end = today + timedelta(days=_MAX_PLAN_DAYS - 1)
    if any(task.due_date < today or task.due_date > window_end for task in tasks):
        return ["상세 일정이 30일 범위를 벗어남"]
    deadline = parsed_goal.get("deadline")
    expected_end = min(deadline, window_end) if deadline else window_end
    if tasks[-1].due_date != expected_end:
        return ["마지막 일정 날짜가 상세 플랜 종료일과 다름"]
    return []


def _normalize_goal_tag(value: Any) -> str:
    tag = str(value or "목표").strip()

    # 태그 의미 생성은 LLM 에 맡기고, 여기서는 DB 저장 가능한 짧은 문자열로만 정리한다.
    tag = re.sub(r"^(나|저|내|제)+", "", tag)
    tag = re.sub(r"(으로|로|에서|에게|한테|부터|까지|하고|이랑|랑|을|를|은|는|이|가|에)$", "", tag)
    tag = re.sub(r"[\s/\\,.?!~]+", "", tag)
    return (tag or "목표")[:20]
