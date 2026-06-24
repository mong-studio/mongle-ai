"""의도별 슬롯 스키마 뱅크 (설계서 §3.2, D2).

각 plan_kind 의 필수/선택 슬롯을 선언적으로 정의한다. judge_sufficiency 가
plan_kind 를 분류한 뒤 이 뱅크로 "필수 슬롯이 다 찼는지"를 판정한다.
exam 엔트리는 기존 goal_rules 의 시험 전용 휴리스틱을 대체한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Slot:
    key: str
    question_hint: str  # follow_up 질문 생성 힌트
    priority: int       # 작을수록 먼저 묻는다


@dataclass(frozen=True)
class PlanSchema:
    plan_kind: str
    required: tuple[Slot, ...]
    optional: tuple[Slot, ...]


SLOT_SCHEMAS: dict[str, PlanSchema] = {
    "exam": PlanSchema(
        "exam",
        required=(
            Slot("exam_part", "필기/실기 중 어떤 시험인지", 1),
            Slot("exam_date", "시험일 또는 남은 기간", 2),
            Slot("daily_hours", "하루 공부 가능 시간", 3),
            Slot("current_level", "현재 진도/수준", 4),
            Slot("background", "전공자/비전공자 여부", 5),
        ),
        optional=(
            Slot("weak_subjects", "약한 과목", 6),
            Slot("goal", "목표 점수/결과", 7),
        ),
    ),
    "event": PlanSchema(
        "event",
        required=(
            Slot("activity", "어떤 경기나 대회에 출전하는지", 1),
            Slot("event_date", "경기일 또는 남은 기간", 2),
            Slot("current_level", "현재 운동 수준과 관련 경험", 3),
            Slot("weekly_cadence", "주 몇 회 훈련 가능한지", 4),
        ),
        optional=(
            Slot("distance", "출전 종목과 거리", 5),
            Slot("constraints", "부상이나 훈련 제약", 6),
            Slot("goal", "완주 또는 기록 목표", 7),
        ),
    ),
    "routine": PlanSchema(
        "routine",
        required=(
            Slot("activity", "무슨 활동인지", 1),
            Slot("cadence", "주 몇 회 또는 어떤 요일인지", 2),
        ),
        optional=(
            Slot("time_of_day", "시간대", 3),
            Slot("horizon", "언제까지", 4),
        ),
    ),
    "vague_goal": PlanSchema(
        "vague_goal",
        required=(
            Slot("goal", "이루고 싶은 목표", 1),
            Slot("first_action", "지금 가장 걸리는 점 / 첫 행동", 2),
            Slot("weekly_cadence", "주간 빈도", 3),
        ),
        optional=(Slot("horizon", "언제까지", 4),),
    ),
    "lifestyle": PlanSchema(
        "lifestyle",
        required=(
            Slot("domains", "어떤 영역들(운동·공부·휴식 등)", 1),
            Slot("cadence_per_domain", "영역별 빈도/시간", 2),
            Slot("horizon", "기간", 3),
        ),
        optional=(
            Slot("fixed_blocks", "고정 일정", 4),
            Slot("priority_order", "우선순위", 5),
        ),
    ),
    "project": PlanSchema(
        "project",
        required=(
            Slot("goal", "구체적으로 무엇을 해내고 싶은지", 1),
            Slot("success_criteria", "어떤 상태가 되면 목표를 달성한 것인지", 2),
            Slot("horizon", "언제까지 준비하거나 실행할지", 3),
            Slot("available_time", "계획에 쓸 수 있는 시간이나 빈도", 4),
        ),
        optional=(
            Slot("current_state", "현재 준비 상태나 경험", 5),
            Slot("constraints", "반드시 고려할 제약이나 고정 일정", 6),
        ),
    ),
}


def missing_required(plan_kind: str, filled_keys: set[str]) -> list[str]:
    """plan_kind 의 미충족 필수 슬롯 key 를 우선순위 순으로 돌려준다.

    알 수 없는 plan_kind 는 project 스키마로 처리한다.
    """
    schema = SLOT_SCHEMAS.get(plan_kind, SLOT_SCHEMAS["project"])
    ordered = sorted(schema.required, key=lambda s: s.priority)
    return [s.key for s in ordered if s.key not in filled_keys]


def slot_hints(plan_kind: str | None, keys: list[str]) -> list[str]:
    """미충족 슬롯 key 를 사람용 한국어 질문 힌트로 바꾼다.

    스키마에 없는 key(예: exam 의 'deadline')는 원문 그대로 둔다.
    """
    schema = SLOT_SCHEMAS.get(plan_kind or "", SLOT_SCHEMAS["project"])
    by_key = {s.key: s.question_hint for s in (*schema.required, *schema.optional)}
    return [by_key.get(k, k) for k in keys]
