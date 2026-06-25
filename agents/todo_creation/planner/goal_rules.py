from __future__ import annotations

from dataclasses import dataclass

from agents.todo_creation.planner.date_parser import (
    has_explicit_deadline,
    parse_explicit_deadline,
)
from agents.todo_creation.planner.slot_schemas import missing_required
from agents.todo_creation.planner.state import PlannerGraphState
from agents.todo_creation.state import ParsedGoal, Turn

_AMBIGUOUS_DEADLINE_WORDS = ("곧", "조만간", "언젠가", "나중에", "머지않아")
_DEADLINE_SENSITIVE_WORDS = ("시험", "마감", "발표", "면접", "여행", "결혼식", "행사")
_EXPLICIT_EXAM_WORDS = ("시험", "자격증", "필기", "실기", "합격", "점수")


@dataclass(frozen=True)
class SupportedExamDomain:
    name: str
    default_tag: str
    aliases: tuple[str, ...]


SUPPORTED_EXAM_DOMAINS = (
    SupportedExamDomain(
        name="정보처리기사",
        default_tag="정보처리기사",
        aliases=("정처기", "정보처리기사", "정보 처리 기사"),
    ),
)
_EXAM_PART_TERMS = ("필기", "실기")
_BACKGROUND_TERMS = ("전공자", "비전공자", "컴공", "전공", "비전공")
_CURRENT_LEVEL_TERMS = (
    "처음",
    "시작",
    "아직",
    "개념",
    "기출",
    "모의고사",
    "1회독",
    "2회독",
    "3회독",
    "회독",
    "완료",
    "끝냈",
    "봤",
    "풀었",
    "공부했",
    "공부 안",
    "SQL",
)
_DAILY_HOURS_TERMS = ("하루", "매일", "시간", "분", "평일", "주말")
_COMPETITION_EVENT_TERMS = (
    "철인삼종",
    "철인 삼종",
    "트라이애슬론",
    "마라톤",
    "하프마라톤",
    "대회 출전",
    "대회에 출전",
    "경기 출전",
    "경기에 출전",
    "레이스",
)
_EVENT_LEVEL_TERMS = (
    "초보",
    "입문",
    "처음",
    "경험",
    "완주",
    "수영",
    "자전거",
    "러닝",
    "달리기",
    "훈련 중",
)
_WEEKLY_CADENCE_TERMS = ("주 1", "주 2", "주 3", "주 4", "주 5", "주 6", "주 7", "매주")


def collect_user_text(state: PlannerGraphState) -> str:
    """현재 턴과 이전 user turn 을 하나의 문자열로 합친다."""

    return " ".join(
        [
            str(state.get("message", "")),
            *[
                str(turn.get("content", ""))
                for turn in state.get("history", [])
                if turn.get("role") == "user"
            ],
        ]
    )


def is_supported_exam_context(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None = None
) -> bool:
    """지원하는 시험 맥락이 대화/목표 어디엔가 명시됐는지 확인한다."""

    text = _compact(
        " ".join(
            [
                collect_user_text(state),
                str((parsed_goal or {}).get("goal_text") or ""),
                str((parsed_goal or {}).get("goal_tag") or ""),
                str((parsed_goal or {}).get("slots") or ""),
            ]
        )
    )
    return any(
        _compact(alias) in text
        for domain in SUPPORTED_EXAM_DOMAINS
        for alias in domain.aliases
    )


def has_explicit_exam_context(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None = None
) -> bool:
    """현재 대화에 실제 시험 준비를 뜻하는 표현이 있는지 확인한다."""

    text = _compact(
        " ".join(
            [
                collect_user_text(state),
                str((parsed_goal or {}).get("goal_text") or ""),
            ]
        )
    )
    return any(_compact(word) in text for word in _EXPLICIT_EXAM_WORDS)


def is_competition_event_context(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None = None
) -> bool:
    """경기·대회 출전 목표를 시험 준비와 분리한다."""

    text = _compact(
        " ".join(
            [
                collect_user_text(state),
                str((parsed_goal or {}).get("goal_text") or ""),
                str((parsed_goal or {}).get("goal_tag") or ""),
                str((parsed_goal or {}).get("slots") or ""),
            ]
        )
    )
    return any(_compact(term) in text for term in _COMPETITION_EVENT_TERMS)


def normalize_competition_event_goal(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None
) -> ParsedGoal:
    """모델이 exam 으로 오분류해도 대회 출전 목표를 event 로 고정한다."""

    goal: ParsedGoal = parsed_goal.copy() if parsed_goal is not None else {}
    goal["intent"] = "plan"
    goal["plan_kind"] = "event"
    goal["goal_text"] = goal.get("goal_text") or latest_user_goal(
        state.get("history", []), state.get("message", "")
    )
    slots = goal.get("slots")
    goal["slots"] = slots if isinstance(slots, dict) else {}
    merge_deadline_from_state(state, goal)
    return goal


def required_competition_event_missing(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None
) -> list[str]:
    """대회 준비 플랜에 필요한 최소 정보를 코드로 검증한다."""

    goal = parsed_goal or {}
    slots = goal.get("slots") or {}
    if not isinstance(slots, dict):
        slots = {}
    text = collect_user_text(state)
    compact_text = _compact(text)
    filled = {
        k
        for k, value in slots.items()
        if k != "event_date" and value not in (None, "", [], {})
    }

    if is_competition_event_context(state, goal):
        filled.add("activity")
    if _has_explicit_deadline(text, state=state):
        filled.add("event_date")
    if any(_compact(term) in compact_text for term in _EVENT_LEVEL_TERMS):
        filled.add("current_level")
    if any(_compact(term) in compact_text for term in _WEEKLY_CADENCE_TERMS):
        filled.add("weekly_cadence")
    return missing_required("event", filled)


def required_supported_exam_missing(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None
) -> list[str]:
    """지원 시험 플랜 생성 전에 반드시 받아야 하는 슬롯을 코드로 강제한다."""

    goal = parsed_goal or {}
    slots = goal.get("slots") or {}
    if not isinstance(slots, dict):
        slots = {}

    text = collect_user_text(state)
    compact_text = _compact(text)
    filled = {
        k
        for k, value in slots.items()
        if k != "exam_date" and value not in (None, "", [], {})
    }

    if any(term in compact_text for term in _EXAM_PART_TERMS):
        filled.add("exam_part")
    if _has_explicit_deadline(text, state=state):
        filled.add("exam_date")
    if any(term in compact_text for term in _DAILY_HOURS_TERMS):
        filled.add("daily_hours")
    if any(_compact(term) in compact_text for term in _CURRENT_LEVEL_TERMS):
        filled.add("current_level")
    if any(_compact(term) in compact_text for term in _BACKGROUND_TERMS):
        filled.add("background")

    return missing_required("exam", filled)


def normalize_supported_exam_goal(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None
) -> ParsedGoal:
    """지원 시험 플래너의 목표 형태를 exam 스키마로 고정한다."""

    goal: ParsedGoal = parsed_goal.copy() if parsed_goal is not None else {}
    goal["intent"] = "plan"
    goal["plan_kind"] = "exam"
    goal["goal_text"] = goal.get("goal_text") or latest_user_goal(
        state.get("history", []), state.get("message", "")
    )
    goal["goal_tag"] = goal.get("goal_tag") or _default_supported_exam_tag(state, goal)
    slots = goal.get("slots")
    goal["slots"] = slots if isinstance(slots, dict) else {}
    merge_deadline_from_state(state, goal)
    return goal


def _default_supported_exam_tag(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None
) -> str:
    text = _compact(
        " ".join(
            [
                collect_user_text(state),
                str((parsed_goal or {}).get("goal_text") or ""),
                str((parsed_goal or {}).get("goal_tag") or ""),
            ]
        )
    )
    for domain in SUPPORTED_EXAM_DOMAINS:
        if any(_compact(alias) in text for alias in domain.aliases):
            return domain.default_tag
    return "시험"


def latest_user_goal(history: list[Turn], fallback: str) -> str:
    """반복 질문 fallback 에서 가장 최근 user 목표를 우선 사용한다."""

    for turn in history:
        if turn.get("role") == "user" and str(turn.get("content", "")).strip():
            return str(turn.get("content", "")).strip()
    return fallback


def _compact(value: str) -> str:
    return "".join(value.split())


def build_recovery_goal(state: PlannerGraphState) -> ParsedGoal:
    """LLM 이 out_of_scope 로 오판해도 기존 목표 정보를 유지한다."""

    previous: ParsedGoal = state.get("parsed_goal") or {}
    goal_text = previous.get("goal_text") or latest_user_goal(
        state.get("history", []), state.get("message", "")
    )
    parsed_goal: ParsedGoal = previous.copy()
    parsed_goal["intent"] = "plan"
    parsed_goal["goal_text"] = goal_text or "목표"
    parsed_goal["deadline"] = previous.get("deadline")
    parsed_goal["daily_capacity_minutes"] = previous.get("daily_capacity_minutes")
    parsed_goal["user_profile_memory"] = state.get("user_profile_memory") or {}
    merge_deadline_from_state(state, parsed_goal)
    return parsed_goal


def merge_deadline_from_state(
    state: PlannerGraphState, parsed_goal: ParsedGoal
) -> None:
    """사용자 대화에서 확인된 날짜만 goal과 날짜 슬롯에 반영한다."""

    today = state.get("today")
    if today is None:
        return
    user_text = collect_user_text(state)
    deadline = parse_explicit_deadline(user_text, today=today)
    if deadline is not None:
        parsed_goal["deadline"] = deadline
        slots = parsed_goal.get("slots")
        if isinstance(slots, dict):
            date_key = (
                "event_date"
                if parsed_goal.get("plan_kind") == "event"
                else "exam_date" if parsed_goal.get("plan_kind") == "exam" else None
            )
            if date_key is not None:
                slots[date_key] = deadline.isoformat()
        return

    if _has_explicit_deadline(user_text, state=state):
        # "8월 말", "이번 달"처럼 코드가 아직 정확한 일자로 계산하지 못하는
        # 표현은 모델이 해석한 값을 보존하되, 날짜 표현 자체가 없으면 신뢰하지 않는다.
        return

    parsed_goal["deadline"] = None
    slots = parsed_goal.get("slots")
    if isinstance(slots, dict):
        slots.pop("event_date", None)
        slots.pop("exam_date", None)


def delegates_planning(message: str) -> bool:
    """사용자가 플래너에게 세부 구성을 맡기는지 판별한다."""

    compact = "".join(str(message).split())
    delegate_words = ("추천해줘", "알아서", "정해줘", "짜줘", "계획해줘", "네가해줘")
    return any(word in compact for word in delegate_words)


def should_accept_out_of_scope(state: PlannerGraphState) -> bool:
    """아주 짧고 명백히 무관한 첫 입력만 out_of_scope 로 수용한다."""

    history = state.get("history", [])
    message = str(state.get("message", "")).strip()
    user_turns = [
        str(turn.get("content", "")).strip()
        for turn in history
        if turn.get("role") == "user" and str(turn.get("content", "")).strip()
    ]
    if len(user_turns) >= 2:
        return False
    if len(message) >= 18:
        return False
    return True


def needs_deadline_follow_up(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None
) -> bool:
    """날짜가 애매한 중요한 목표는 계획 대신 deadline 질문으로 되돌린다."""

    text = collect_user_text(state)
    has_ambiguous_deadline = any(word in text for word in _AMBIGUOUS_DEADLINE_WORDS)
    has_deadline_sensitive_goal = any(word in text for word in _DEADLINE_SENSITIVE_WORDS)
    if has_ambiguous_deadline and has_deadline_sensitive_goal:
        return not _has_explicit_deadline(text, state=state)
    return bool(
        has_deadline_sensitive_goal
        and parsed_goal
        and not parsed_goal.get("deadline")
        and not _has_explicit_deadline(text, state=state)
    )


def _has_explicit_deadline(text: str, *, state: PlannerGraphState) -> bool:
    """절대 날짜/상대 날짜가 있으면 계획 생성으로 진행한다."""

    today = state.get("today")
    if today is not None and has_explicit_deadline(text, today=today):
        return True
    explicit_words = ("이번달", "다음달")
    if any(word in text.replace(" ", "") for word in explicit_words):
        return True
    date_markers = ("일 뒤", "주 뒤", "개월 뒤", "월", "-")
    return any(char.isdigit() for char in text) and any(marker in text for marker in date_markers)
