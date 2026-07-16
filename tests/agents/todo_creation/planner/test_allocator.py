from datetime import date, timedelta

from agents.todo_creation.planner.allocator import (
    cadence_is_specific,
    expand_routine,
    parse_daily_time,
    recover_cadence,
)


def test_recover_cadence_from_message() -> None:
    # 모델이 "매주 3회"를 "weekly"로 뭉개도 원문 빈도에서 "주 3회" 복구
    assert recover_cadence("매주 3회 물 마실거야") == "주 3회"
    assert recover_cadence("일주일에 2번") == "주 2회"
    # 빈도가 없으면 None → follow_up 되묻기에 맡긴다
    assert recover_cadence("weekly") is None
    assert recover_cadence("매주") is None
    assert recover_cadence("") is None


def test_recover_cadence_weekdays_and_daily() -> None:
    # 연속 요일 글자(월수금)는 cadence 로 복구
    assert recover_cadence("월수금 러닝 시작할래") == "월수금"
    assert recover_cadence("화목 요가") == "화목"
    # "매일" 은 daily cadence
    assert recover_cadence("매일 아침 30분 독서") == "매일"


def test_recover_cadence_no_false_positive_on_dates() -> None:
    # 단일 요일 글자(금요일/토요일/일주일)는 날짜라 cadence 로 오탐하지 않는다
    assert recover_cadence("이번 주 금요일까지") is None
    assert recover_cadence("토요일에 등산") is None
    assert recover_cadence("일주일 뒤에") is None


def test_parse_daily_time() -> None:
    assert parse_daily_time("하루 2시간 정도 낼 수 있어") == "하루 2시간"
    assert parse_daily_time("매일 1시간씩") == "하루 1시간"
    assert parse_daily_time("하루 30분") == "하루 30분"
    assert parse_daily_time("하루에 3시간") == "하루 3시간"
    # 기간 표현 없으면 None
    assert parse_daily_time("그냥 운동하고 싶어") is None
    assert parse_daily_time("") is None


def test_cadence_is_specific_true_for_count_weekday_daily() -> None:
    assert cadence_is_specific("주3회")
    assert cadence_is_specific("주 3회")
    assert cadence_is_specific("월수금")
    assert cadence_is_specific("매주 월요일")
    assert cadence_is_specific("매일")


def test_cadence_is_specific_false_for_vague() -> None:
    # 빈도(주 N회)도 명시 요일도 없는 표현 → 모호(주 몇 회 되물어야 함)
    assert not cadence_is_specific("매주")
    assert not cadence_is_specific("꾸준히")
    assert not cadence_is_specific("")


def test_weekly_count_expands_across_horizon() -> None:
    today = date(2026, 6, 1)
    out = expand_routine("헬스", "주 3회", today=today, horizon_days=28)
    assert len(out) == 12  # 3회/주 × 4주
    assert all(today <= c.due_date < today + timedelta(days=28) for c in out)
    assert len({c.due_date.weekday() for c in out}) == 3  # 매주 같은 3요일


def test_explicit_weekdays_parsed() -> None:
    today = date(2026, 6, 1)
    out = expand_routine("러닝", "월수금", today=today, horizon_days=7)
    assert {c.due_date.weekday() for c in out} == {0, 2, 4}
    assert len(out) == 3


def test_routine_items_are_assigned_in_weekday_order() -> None:
    today = date(2026, 6, 1)
    out = expand_routine(
        "운동",
        "월수금",
        today=today,
        horizon_days=7,
        routine_items=["상체", "하체", "전신"],
    )

    assert [(c.due_date.weekday(), c.title) for c in out] == [
        (0, "상체"),
        (2, "하체"),
        (4, "전신"),
    ]


def test_clamps_to_deadline() -> None:
    today = date(2026, 6, 1)
    deadline = date(2026, 6, 14)
    out = expand_routine("헬스", "주 3회", today=today, horizon_days=28, deadline=deadline)
    assert out  # 일부는 생성됨
    assert all(c.due_date <= deadline for c in out)


def test_title_truncated_and_tagged() -> None:
    out = expand_routine(
        "아침스트레칭아주아주아주아주아주길게", "주1", today=date(2026, 6, 1), horizon_days=7
    )
    assert out
    assert all(len(c.title) <= 20 for c in out)
    assert all("루틴" in c.tags for c in out)


def test_blank_activity_falls_back_to_default_title() -> None:
    out = expand_routine("   ", "주1", today=date(2026, 6, 1), horizon_days=7)
    assert out
    assert all(c.title == "루틴" for c in out)


def test_parse_horizon_days():
    from agents.todo_creation.planner.allocator import parse_horizon_days
    assert parse_horizon_days("이걸 두 달짜리로 늘려줘") == 60
    assert parse_horizon_days("8주간 진행") == 56
    assert parse_horizon_days("한 달 동안") == 30
    assert parse_horizon_days("3개월 계획") == 90
    assert parse_horizon_days("그냥 헬스하고싶어") is None
    assert parse_horizon_days("") is None


def test_parse_tag_override():
    from agents.todo_creation.planner.allocator import parse_tag_override
    assert parse_tag_override("태그를 운동으로 바꿔줘") == "운동"
    assert parse_tag_override("태그 공부로 변경해줘") == "공부"
    assert parse_tag_override("월수금 헬스 하고싶어") is None
    assert parse_tag_override("") is None
