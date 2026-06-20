"""exam 케이스 → 구조화 플랜(PlanOutput) 템플릿.

assistant 출력은 런타임 GenerateResult 미러(plan_schemas.PlanOutput) JSON 이다.
- 전략 내러티브(크롤 evidence 기반 actual_plan_summary)는 summary_text 에 담고,
- todos/calendar_events 는 페이즈 구조(개념→기출→오답→총정리)로 분해한다.
  'N단원 풀기' 식 단조 분해를 만들지 않는 것이 목적이다.
"""

from __future__ import annotations

from datetime import date, timedelta

from sft_pipeline.build.lib.plan_schemas import PlanOutput, PlanTask


def _field(case: dict, key: str, default: str = "미기재") -> str:
    value = (case.get(key) or "").strip()
    return value or default


# instruction augmentation 풀. 인덱스로 결정론적 회전해 표현 다양성을 확보
# (단일 표현 과적합 방지 / 데이터셋 재현성 유지)
_INSTRUCTIONS = (
    "다음 조건에 맞는 단기 시험 준비 계획을 세워줘.",
    "아래 상황에 맞춰 짧은 기간 동안의 시험 공부 계획을 짜줘.",
    "주어진 조건을 보고 단기간 시험 대비 학습 플랜을 만들어줘.",
    "다음 정보를 바탕으로 시험까지 남은 기간의 공부 일정을 제안해줘.",
)

_MAX_PLAN_DAYS = 30  # 단기 시험 대상


def build_instruction(case: dict, index: int = 0) -> str:
    return _INSTRUCTIONS[index % len(_INSTRUCTIONS)]


def build_input(case: dict, today: date) -> str:
    return (
        f"시험: {_field(case, 'exam_type')} / "
        f"남은 기간: {_field(case, 'time_left')} / "
        f"하루 가용: {_field(case, 'daily_hours')} / "
        f"시작 수준: {_field(case, 'start_level')} / "
        f"목표: {_field(case, 'goal')} / "
        f"특이사항: {_field(case, 'special_notes')} / "
        f"기준일(오늘): {today.isoformat()}"
    )


def _plan_days(case: dict) -> int:
    try:
        days = int(case.get("time_left_days") or 0)
    except (ValueError, TypeError):
        days = 0
    if days <= 0:
        days = 7
    return min(days, _MAX_PLAN_DAYS)


def _phase_titles(days: int) -> list[str]:
    """일별 페이즈 제목. 실제 후기의 전략 구조(개념→기출→오답→총정리)를 따른다."""
    if days <= 1:
        return ["기출·오답 총정리"]
    if days == 2:
        return ["핵심 개념·기출 훑기", "총정리·최종 점검"]
    if days == 3:
        return ["핵심 개념·기출 훑기", "오답 정리·반복", "총정리·최종 점검"]
    middle = [f"기출 {k}회차 풀이" for k in range(1, days - 2)]
    return ["핵심 개념 훑기", *middle, "오답 정리·반복", "총정리·최종 점검"]


def _build_summary(case: dict) -> str:
    exam = _field(case, "exam_type")
    period = _field(case, "time_left")
    daily = _field(case, "daily_hours")
    level = _field(case, "start_level")
    goal = _field(case, "goal")
    strategy = _field(case, "actual_plan_summary", default="")
    notes = _field(case, "special_notes", default="")

    parts = [f"[{exam} · {period} · {daily}] 시작 수준 {level} 기준, 목표 '{goal}'."]
    if strategy:
        parts.append(f"전략: {strategy}.")
    if notes:
        parts.append(f"유의: {notes} 상황이니 무리한 분량보다 반복에 집중하세요.")
    return " ".join(parts)[:1500]


def build_plan(case: dict, today: date) -> PlanOutput:
    """케이스 → 정합성 있는 구조화 플랜. due_date==today → todos, 미래 → calendar_events."""
    days = _plan_days(case)
    tasks = [
        PlanTask(title=title, due_date=today + timedelta(days=i), tags=["공부"])
        for i, title in enumerate(_phase_titles(days))
    ]
    return PlanOutput(
        summary_text=_build_summary(case),
        todos=[t for t in tasks if t.due_date == today],
        calendar_events=[t for t in tasks if t.due_date != today],
    )


def build_output(case: dict, today: date) -> str:
    """assistant content 로 쓸 구조화 플랜 JSON 문자열."""
    return build_plan(case, today).model_dump_json()
