from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.domain_knowledge import recommended_task_titles_for_goal
from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.planner.allocator import expand_routine
from agents.todo_creation.planner.conversation_style import render_chief_voice
from agents.todo_creation.planner.goal_rules import (
    SUPPORTED_EXAM_DOMAINS,
)
from agents.todo_creation.planner.state import PlannerGraphState
from agents.todo_creation.schemas import MAX_TAG_LENGTH, TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay

_MAX_SUMMARY_CHARS = 1500
_DEFAULT_ROUTINE_HORIZON = 28
_MAX_PLAN_DAYS = 30
_MAX_TASKS = 15
_EXAM_CONTAMINATION_TERMS = (
    "필기",
    "실기",
    "기출",
    "시험",
    "과목",
    *(
        alias
        for domain in SUPPORTED_EXAM_DOMAINS
        for alias in domain.aliases
    ),
)
_GENERIC_TITLE_FILLERS = ("훈련", "연습", "준비", "시작", "계획", "세우기", "체크")
_EXAM_PARTS = ("필기", "실기")
_HANGUL_RE = re.compile(r"[가-힣]")
_D_DAY_RE = re.compile(r"\bD\s*-\s*\d+\b", re.IGNORECASE)
_NUMERIC_TOKEN_RE = re.compile(r"\d+")
_OPAQUE_SYMBOL_RE = re.compile(
    r"\b(?:\d+[A-Z][A-Z0-9]*|[A-Z]{2,}[A-Z0-9]*|[A-Z]+[0-9]+[A-Z0-9]*)\b"
)

log = logging.getLogger(__name__)


async def plan_generator_node(
    state: PlannerGraphState, config: RunnableConfig
) -> dict[str, Any]:
    ports = get_ports(config)
    parsed_goal: ParsedGoal = state.get("parsed_goal") or {}
    today = state["today"]

    # routine: cadence 를 horizon 으로 결정적 전개(LLM 생략, 설계서 §3.4).
    if parsed_goal.get("plan_kind") == "routine":
        return _routine_plan(parsed_goal, today=today)

    # LoRA는 검증된 시험 도메인에만 사용한다. 범용 목표를 base 모델로
    # 격리해 시험 특화 학습 내용이 다른 계획으로 새는 것을 막는다.
    llm = _select_generator(ports, state=state, parsed_goal=parsed_goal)
    goal_tag = _normalize_goal_tag(parsed_goal.get("goal_tag"))
    if not goal_tag:
        goal_tag = await llm.generate_goal_tag(
            parsed_goal=parsed_goal,
            history=state.get("history", []),
        )
    parsed_goal = {**parsed_goal, "goal_tag": goal_tag}
    summary_text, plan, used_safe_fallback = await _generate_plan_with_base_fallback(
        llm,
        ports=ports,
        parsed_goal=parsed_goal,
        today=today,
    )
    if len(summary_text) > _MAX_SUMMARY_CHARS:
        summary_text, plan, used_safe_fallback = await _generate_plan_with_base_fallback(
            llm,
            ports=ports,
            parsed_goal=parsed_goal,
            today=today,
        )
    summary_text, tagged_plan = _prepare_generated_plan(
        summary_text, plan, parsed_goal=parsed_goal, today=today
    )
    issues = []
    if not used_safe_fallback:
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
        summary_text, plan, used_safe_fallback = await _generate_plan_with_base_fallback(
            llm,
            ports=ports,
            parsed_goal=corrected_goal,
            today=today,
        )
        summary_text, tagged_plan = _prepare_generated_plan(
            summary_text, plan, parsed_goal=parsed_goal, today=today
        )
        issues = []
        if not used_safe_fallback:
            issues = await _validation_issues(
                getattr(ports, "validator", None),
                plan=tagged_plan,
                summary_text=summary_text,
                parsed_goal=parsed_goal,
                today=today,
            )
        if issues:
            blocking_issues = _deterministic_issues(
                tagged_plan,
                summary_text=summary_text,
                parsed_goal=parsed_goal,
                today=today,
            )
            if blocking_issues:
                fallback_summary, fallback_plan = _deterministic_fallback_plan(
                    parsed_goal,
                    today=today,
                    issues=blocking_issues,
                )
                fallback_issues = _deterministic_issues(
                    fallback_plan,
                    summary_text=fallback_summary,
                    parsed_goal=parsed_goal,
                    today=today,
                )
                if fallback_issues:
                    raise LLMOutputError(
                        "plan quality validation failed after retry: "
                        + "; ".join(blocking_issues)
                    )
                log.warning(
                    "using deterministic fallback plan after blocking issues: %s",
                    "; ".join(blocking_issues),
                )
                summary_text = fallback_summary
                tagged_plan = fallback_plan
            log.warning(
                "semantic plan validation remained advisory after retry: %s",
                "; ".join(issues),
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


async def _generate_plan_with_base_fallback(
    generator: Any,
    *,
    ports: Any,
    parsed_goal: ParsedGoal,
    today: date,
) -> tuple[str, list[PlanDay], bool]:
    try:
        summary, plan = await generator.generate_plan(
            parsed_goal=parsed_goal, today=today
        )
        return summary, plan, False
    except LLMOutputError as err:
        fallback = getattr(ports, "classifier", None)
        if fallback is not None and fallback is not generator:
            try:
                log.warning("planner output invalid; retrying once with base model: %s", err)
                summary, plan = await fallback.generate_plan(
                    parsed_goal=parsed_goal, today=today
                )
                return summary, plan, False
            except LLMOutputError as fallback_err:
                log.warning("base planner fallback output invalid: %s", fallback_err)
        log.warning("planner output invalid; using deterministic fallback: %s", err)
        summary, plan = _deterministic_fallback_seed(parsed_goal, today=today)
        return summary, plan, True


def _routine_plan(parsed_goal: ParsedGoal, *, today: date) -> dict[str, Any]:
    """routine plan_kind 을 코드로 전개한다 — cadence 를 horizon 내 날짜로 펼침.

    LLM 을 전혀 호출하지 않는다(설계서 §3.4: 슬롯이 곧 내용). judge 가 채운
    goal_tag 로 일괄 태깅하고, 마감일 이후는 expand_routine 이 clamp 한다.
    """
    slots = parsed_goal.get("slots") or {}
    activity = str(slots.get("activity") or parsed_goal.get("goal_text") or "루틴")
    cadence = str(slots.get("cadence") or "")
    raw_routine_items = slots.get("routine_items")
    routine_items = (
        [str(item) for item in raw_routine_items]
        if isinstance(raw_routine_items, list)
        else None
    )
    horizon = _routine_horizon(slots.get("horizon"))
    goal_tag = _normalize_goal_tag(parsed_goal.get("goal_tag"))
    deadline = parsed_goal.get("deadline")

    events = [
        event.model_copy(update={"tags": [goal_tag]})
        for event in expand_routine(
            activity,
            cadence,
            today=today,
            horizon_days=horizon,
            deadline=deadline,
            routine_items=routine_items,
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

    detailed_end = min(max(today, deadline), window_end)
    dates = _spread_dates(today, detailed_end, len(tasks), single_at_end=True)
    return _group_scheduled_tasks(tasks, dates)


def _spread_dates(
    start: date, end: date, count: int, *, single_at_end: bool
) -> list[date]:
    if count <= 0:
        return []
    if count == 1:
        return [end if single_at_end else start]
    span = (end - start).days
    return [
        start + timedelta(days=round(span * index / (count - 1)))
        for index in range(count)
    ]


def _group_scheduled_tasks(
    tasks: list[TaskCandidate], dates: list[date]
) -> list[PlanDay]:
    grouped: dict[date, list[TaskCandidate]] = {}
    for task, planned_date in zip(tasks, dates, strict=True):
        grouped.setdefault(planned_date, []).append(
            task.model_copy(update={"due_date": planned_date})
        )
    return [
        {"date": planned_date, "tasks": grouped[planned_date]}
        for planned_date in sorted(grouped)
    ]


def _deterministic_fallback_plan(
    parsed_goal: ParsedGoal, *, today: date, issues: list[str]
) -> tuple[str, list[PlanDay]]:
    """LLM이 재시도 후에도 깨질 때 쓰는 최소 안전 플랜.

    특정 시험·경기명을 코드에 박지 않고 현재 분류와 수집된 슬롯만 사용한다.
    서비스에서는 빈 응답이나 예외보다, 오염 없는 짧은 초안을 반환한 뒤 사용자가
    재생성·수정할 수 있게 하는 편이 안전하다.
    """

    summary, plan = _deterministic_fallback_seed(parsed_goal, today=today)
    summary = _append_plan_context(summary, parsed_goal=parsed_goal, today=today)
    return _render_summary(summary), plan


def _deterministic_fallback_seed(
    parsed_goal: ParsedGoal, *, today: date
) -> tuple[str, list[PlanDay]]:
    """생성 실패를 일반 생성 경로로 되돌리기 위한 원시 안전 초안."""

    plan_kind = str(parsed_goal.get("plan_kind") or "project")
    goal_tag = _normalize_goal_tag(
        parsed_goal.get("goal_tag") or parsed_goal.get("goal_text")
    )
    slots = parsed_goal.get("slots") if isinstance(parsed_goal.get("slots"), dict) else {}
    deadline = parsed_goal.get("deadline")
    window_end = today + timedelta(days=_MAX_PLAN_DAYS - 1)
    detailed_end = min(max(today, deadline), window_end) if deadline else window_end
    titles = _fallback_titles(plan_kind, slots, parsed_goal=parsed_goal)
    tasks = [
        TaskCandidate(title=title, due_date=today, tags=[goal_tag])
        for title in titles[:_MAX_TASKS]
    ]
    plan = _group_scheduled_tasks(
        tasks,
        _spread_dates(today, detailed_end, len(tasks), single_at_end=True),
    )
    summary = (
        "확인된 목표 정보로 바로 실행할 수 있는 기본 초안을 잡았어요."
    )
    return summary, plan


def _fallback_titles(
    plan_kind: str, slots: dict[str, Any], *, parsed_goal: ParsedGoal
) -> list[str]:
    if plan_kind == "exam":
        domain_titles = recommended_task_titles_for_goal(
            parsed_goal, limit=_MAX_TASKS
        )
        if domain_titles:
            return domain_titles
        return [
            "범위 정리 30분",
            "개념 복습 1회",
            "문제 풀이 20문항",
            "오답 정리 1회",
            "최종 점검 30분",
        ]
    if plan_kind == "event":
        cadence = str(slots.get("weekly_cadence") or "주 2회")
        return [
            "현재 수준 기록",
            "기초 체력 30분",
            "기술 동작 20분",
            f"{cadence} 실행",
            "회복 상태 점검",
            "다음 단계 조정",
        ]
    if plan_kind == "project":
        return _project_fallback_titles(parsed_goal, slots)
    return [
        "현재 상태 정리",
        "핵심 작업 1개",
        "초안 만들기 30분",
        "진행 상태 점검",
        "다음 단계 조정",
    ]


def _project_fallback_titles(
    parsed_goal: ParsedGoal, slots: dict[str, Any]
) -> list[str]:
    text = " ".join(
        str(value)
        for value in (
            parsed_goal.get("goal_text"),
            parsed_goal.get("goal_tag"),
            slots.get("goal"),
            slots.get("current_state"),
        )
        if value
    )
    compact = text.replace(" ", "").lower()
    if any(term in compact for term in ("데이터베이스", "database", "db", "sql", "erd")):
        return [
            "요구사항 목록 정리",
            "엔티티 후보 작성",
            "ERD 초안 만들기",
            "테이블 컬럼 정의",
            "샘플 데이터 입력",
            "쿼리 동작 점검",
        ]

    topic = _fallback_topic(parsed_goal, slots)
    if topic == "목표":
        return [
            "현재 상태 정리",
            "핵심 작업 1개",
            "초안 만들기 30분",
            "진행 상태 점검",
            "다음 단계 조정",
        ]
    return [
        f"{topic} 범위 정리",
        f"{topic} 첫 작업 선정",
        f"{topic} 초안 30분",
        f"{topic} 진행 점검",
        f"{topic} 다음 단계 조정",
    ]


def _fallback_topic(parsed_goal: ParsedGoal, slots: dict[str, Any]) -> str:
    for value in (
        slots.get("goal"),
        parsed_goal.get("goal_tag"),
        parsed_goal.get("goal_text"),
    ):
        topic = re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or ""))
        if topic:
            return topic[:8]
    return "목표"


def _append_plan_context(
    summary: str, *, parsed_goal: ParsedGoal, today: date
) -> str:
    parts = [summary.strip()] if summary.strip() else []
    assumptions = parsed_goal.get("assumptions") or []
    if assumptions:
        parts.extend(_sentence(str(item)) for item in assumptions if str(item).strip())
    deadline = parsed_goal.get("deadline")
    window_end = today + timedelta(days=_MAX_PLAN_DAYS - 1)
    if deadline and deadline > window_end:
        parts.append(
            f"상세 일정은 {window_end.isoformat()}까지 제공해요. "
            f"그 이후 {deadline.isoformat()}까지는 목표에 맞춰 실행 범위를 넓히고 "
            "점검하며 마무리하는 흐름으로 이어가면 돼요."
        )
    return " ".join(parts)


def _sentence(value: str) -> str:
    text = value.strip().rstrip(" ,.!?~")
    if not text:
        return ""
    return text + "."


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
    issues = _deterministic_issues(
        plan,
        summary_text=summary_text,
        parsed_goal=parsed_goal,
        today=today,
    )
    if validator is None or issues:
        return issues
    validate = getattr(validator, "validate_plan", None)
    if validate is not None:
        try:
            valid, semantic_issues = await validate(
                plan=plan,
                summary_text=summary_text,
                parsed_goal=parsed_goal,
                today=today,
            )
        except LLMOutputError as err:
            log.warning("semantic plan validator output ignored: %s", err)
            return issues
        if not valid:
            issues.extend(semantic_issues or ["목표 관련성 또는 문장 품질 미달"])
    return list(dict.fromkeys(issues))


def _deterministic_issues(
    plan: list[PlanDay],
    *,
    parsed_goal: ParsedGoal,
    today: date,
    summary_text: str = "",
) -> list[str]:
    tasks = [task for day in plan for task in day.get("tasks", [])]
    if not tasks:
        return ["일정이 비어 있음"]
    if len(tasks) > _MAX_TASKS:
        return [f"일정이 {_MAX_TASKS}개를 초과함"]
    plan_text = " ".join([summary_text, *(task.title for task in tasks)])
    symbol_issue = _off_topic_symbol_issue(tasks, parsed_goal)
    if symbol_issue:
        return [symbol_issue]
    numeric_issue = _numeric_placeholder_title_issue(tasks)
    if numeric_issue:
        return [numeric_issue]
    if parsed_goal.get("plan_kind") != "exam" and any(
        term in plan_text for term in _EXAM_CONTAMINATION_TERMS
    ):
        return ["비시험 목표에 시험 준비 내용이 포함됨"]
    exam_part_issue = _exam_part_mismatch(plan_text, parsed_goal)
    if exam_part_issue:
        return [exam_part_issue]
    if parsed_goal.get("plan_kind") != "routine":
        normalized_titles = [re.sub(r"\s+", "", task.title) for task in tasks]
        if len(tasks) >= 4 and any(
            normalized_titles.count(title) > 2 for title in set(normalized_titles)
        ):
            return ["같은 일정 제목이 과도하게 반복됨"]
        if any(_is_overly_generic_title(task.title, parsed_goal) for task in tasks):
            return ["실행 기준이 없는 포괄적인 일정 제목이 포함됨"]
    window_end = today + timedelta(days=_MAX_PLAN_DAYS - 1)
    deadline = parsed_goal.get("deadline")
    latest_allowed = min(deadline, window_end) if deadline else window_end
    if any(task.due_date < today or task.due_date > latest_allowed for task in tasks):
        return ["일정이 허용 날짜 범위를 벗어남"]
    if deadline and tasks[-1].due_date != latest_allowed:
        return ["마지막 일정 날짜가 상세 플랜 종료일과 다름"]
    # ponytail: Latin blocking 제거 — "Python", "GitHub" 같은 정상 기술 용어를 false positive 로
    # 잡아 deterministic fallback 으로 빠지는 문제. 언어 품질은 semantic validator 에 위임하고,
    # 생성 단계의 guided schema 는 구조/길이만 제한한다.
    return []


def _off_topic_symbol_issue(
    tasks: list[TaskCandidate], parsed_goal: ParsedGoal
) -> str | None:
    """목표 문맥에 없는 대문자/숫자 코드형 제목이 플랜을 지배하면 차단한다."""

    context = _compact_goal_context(parsed_goal)
    for task in tasks:
        title = task.title.strip()
        if _HANGUL_RE.search(title):
            continue
        unknown = [
            token
            for token in _OPAQUE_SYMBOL_RE.findall(title)
            if token.upper() not in context
        ]
        has_ratio = "%" in title
        if len(unknown) >= 2 or (unknown and has_ratio):
            return "목표와 무관한 코드형 일정 제목이 포함됨"
    return None


def _numeric_placeholder_title_issue(tasks: list[TaskCandidate]) -> str | None:
    """숫자·D-day만으로 된 제목은 실행 단위가 아니므로 차단한다."""

    for task in tasks:
        title = task.title.strip()
        if _HANGUL_RE.search(title) or not any(char.isdigit() for char in title):
            continue
        number_count = len(_NUMERIC_TOKEN_RE.findall(title))
        title_without_d_day = _D_DAY_RE.sub("", title)
        residue = re.sub(r"[\d\s:/.,~%+\-()·]+", "", title_without_d_day)
        if not residue:
            return "의미 없는 숫자 나열 일정 제목이 포함됨"
        if _D_DAY_RE.search(title) and number_count >= 2:
            return "의미 없는 D-day 숫자 일정 제목이 포함됨"
    return None


def _compact_goal_context(parsed_goal: ParsedGoal) -> str:
    values: list[str] = [
        str(parsed_goal.get("goal_text") or ""),
        str(parsed_goal.get("goal_tag") or ""),
    ]
    slots = parsed_goal.get("slots")
    if isinstance(slots, dict):
        values.extend(str(value) for value in slots.values())
    return re.sub(r"[^0-9A-Z가-힣]", "", " ".join(values).upper())


def _exam_part_mismatch(plan_text: str, parsed_goal: ParsedGoal) -> str | None:
    if parsed_goal.get("plan_kind") != "exam":
        return None
    slots = parsed_goal.get("slots")
    if not isinstance(slots, dict):
        return None
    expected = str(slots.get("exam_part") or "").strip()
    if expected not in _EXAM_PARTS:
        return None
    opposite = "실기" if expected == "필기" else "필기"
    if opposite in plan_text:
        return f"시험 구분이 사용자 답변({expected})과 다름"
    return None


def _is_overly_generic_title(title: str, parsed_goal: ParsedGoal) -> bool:
    compact = re.sub(r"[^0-9A-Za-z가-힣]", "", title)
    if any(char.isdigit() for char in compact):
        return False
    goal_tag = re.sub(
        r"[^0-9A-Za-z가-힣]", "", str(parsed_goal.get("goal_tag") or "")
    )
    if goal_tag:
        compact = compact.replace(goal_tag, "")
    for filler in _GENERIC_TITLE_FILLERS:
        compact = compact.replace(filler, "")
    return len(compact) < 2


def _select_generator(
    ports: Any,
    *,
    state: PlannerGraphState,
    parsed_goal: ParsedGoal,
) -> Any:
    if _is_supported_exam_goal(parsed_goal):
        return ports.llm
    return getattr(ports, "classifier", None) or ports.llm


def _is_supported_exam_goal(parsed_goal: ParsedGoal) -> bool:
    """생성 단계에서는 planner가 확정한 exam 목표 자체를 기준으로 선택한다."""

    if parsed_goal.get("plan_kind") != "exam":
        return False
    text = re.sub(
        r"\s+",
        "",
        " ".join(
            str(value or "")
            for value in (parsed_goal.get("goal_text"), parsed_goal.get("goal_tag"))
        ),
    )
    return any(
        re.sub(r"\s+", "", alias) in text
        for domain in SUPPORTED_EXAM_DOMAINS
        for alias in domain.aliases
    )


def _normalize_goal_tag(value: Any) -> str:
    tag = str(value or "목표").strip()

    # 태그 의미 생성은 LLM 에 맡기고, 여기서는 DB 저장 가능한 짧은 문자열로만 정리한다.
    tag = re.sub(r"^(나|저|내|제)+", "", tag)
    tag = re.sub(r"(으로|로|에서|에게|한테|부터|까지|하고|이랑|랑|을|를|은|는|이|가|에)$", "", tag)
    tag = re.sub(r"[\s/\\,.?!~]+", "", tag)
    return (tag or "목표")[:MAX_TAG_LENGTH]
