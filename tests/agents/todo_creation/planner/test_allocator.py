from datetime import date, timedelta

from agents.todo_creation.planner.allocator import expand_routine


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
    assert all("routine" in c.tags for c in out)


def test_blank_activity_falls_back_to_default_title() -> None:
    out = expand_routine("   ", "주1", today=date(2026, 6, 1), horizon_days=7)
    assert out
    assert all(c.title == "루틴" for c in out)
