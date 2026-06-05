from __future__ import annotations


def _field(case: dict, key: str, default: str = "미기재") -> str:
    value = (case.get(key) or "").strip()
    return value or default


# instruction augmentation 풀. 인덱스로 결정론적 회전해 표현 다양성을 확보한다
# (단일 표현 과적합 방지 / 데이터셋 재현성 유지).
_INSTRUCTIONS = (
    "다음 조건에 맞는 단기 시험 준비 계획을 세워줘.",
    "아래 상황에 맞춰 짧은 기간 동안의 시험 공부 계획을 짜줘.",
    "주어진 조건을 보고 단기간 시험 대비 학습 플랜을 만들어줘.",
    "다음 정보를 바탕으로 시험까지 남은 기간의 공부 일정을 제안해줘.",
)


def build_instruction(case: dict, index: int = 0) -> str:
    return _INSTRUCTIONS[index % len(_INSTRUCTIONS)]


def build_input(case: dict) -> str:
    return (
        f"시험: {_field(case, 'exam_type')} / "
        f"남은 기간: {_field(case, 'time_left')} / "
        f"하루 가용: {_field(case, 'daily_hours')} / "
        f"시작 수준: {_field(case, 'start_level')} / "
        f"목표: {_field(case, 'goal')} / "
        f"특이사항: {_field(case, 'special_notes')}"
    )


def build_output(case: dict) -> str:
    exam = _field(case, "exam_type")
    period = _field(case, "time_left")
    daily = _field(case, "daily_hours")
    level = _field(case, "start_level")
    goal = _field(case, "goal")
    summary = _field(case, "actual_plan_summary", default="")
    notes = _field(case, "special_notes", default="")

    lines = [
        f"[{exam} · {period} · {daily} 준비 플랜]",
        f"시작 수준 {level} 기준으로 '{goal}'을(를) 목표로 잡습니다.",
        "",
        "추천 학습 흐름:",
        f"- {summary}" if summary else "- (계획 요약 미기재)",
    ]
    if notes:
        lines.append(f"핵심 유의점: {notes} 상황을 고려해 무리한 분량보다 반복에 집중하세요.")
    return "\n".join(lines)
