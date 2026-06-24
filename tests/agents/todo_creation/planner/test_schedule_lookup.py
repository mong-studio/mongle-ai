"""시험일 해석 훅(§3.6) — 날짜 파싱 + resolve 게이트(fake, 라이브 호출 0)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from agents.todo_creation.planner.schedule_lookup import (
    parse_future_date,
    resolve_exam_deadline,
)

_TODAY = date(2026, 6, 24)


# --- parse_future_date ------------------------------------------------------


def test_parses_iso_and_korean_dates_picking_earliest_future():
    assert parse_future_date("접수 후 2026-08-01, 시험일 2026-07-01", today=_TODAY) == date(
        2026, 7, 1
    )  # 가장 이른 미래
    assert parse_future_date("2026년 7월 1일 시행", today=_TODAY) == date(2026, 7, 1)
    assert parse_future_date("시험은 7월 1일이에요", today=_TODAY) == date(2026, 7, 1)


def test_year_omitted_rolls_to_next_year_if_past():
    # 오늘이 6/24 → "1월 1일"은 올해 과거 → 내년으로.
    assert parse_future_date("1월 1일 예정", today=_TODAY) == date(2027, 1, 1)


def test_past_or_no_date_returns_none():
    assert parse_future_date("지난 회차는 2026-05-01 였다", today=_TODAY) is None
    assert parse_future_date("날짜 정보 없음", today=_TODAY) is None


# --- resolve_exam_deadline 게이트 -------------------------------------------


@dataclass
class _FakeLookup:
    result: date | None = None
    raises: bool = False
    calls: int = 0

    async def next_exam_date(self, *, exam_name, official_domains, today):
        self.calls += 1
        if self.raises:
            raise RuntimeError("boom")
        return self.result


def _exam_goal(**over):
    return {"plan_kind": "exam", "goal_tag": "정보처리기사", "goal_text": "정처기 준비", **over}


async def test_fills_deadline_for_known_exam_future_date():
    goal = _exam_goal()
    lookup = _FakeLookup(result=date(2026, 8, 2))
    filled = await resolve_exam_deadline(goal, today=_TODAY, lookup=lookup)
    assert filled is True
    assert goal["deadline"] == date(2026, 8, 2)
    assert lookup.calls == 1


async def test_no_lookup_is_noop():
    goal = _exam_goal()
    assert await resolve_exam_deadline(goal, today=_TODAY, lookup=None) is False
    assert "deadline" not in goal


async def test_skips_non_exam_without_calling_lookup():
    goal = {"plan_kind": "lifestyle", "goal_tag": "운동"}
    lookup = _FakeLookup(result=date(2026, 8, 2))
    assert await resolve_exam_deadline(goal, today=_TODAY, lookup=lookup) is False
    assert lookup.calls == 0  # 비-시험은 호출조차 안 함(비용 0)


async def test_skips_unknown_exam():
    goal = _exam_goal(goal_tag="사내영어시험", goal_text="회사 영어 시험")
    lookup = _FakeLookup(result=date(2026, 8, 2))
    assert await resolve_exam_deadline(goal, today=_TODAY, lookup=lookup) is False
    assert lookup.calls == 0  # 공식 도메인 모르면 호출 안 함


async def test_existing_deadline_is_not_overwritten():
    goal = _exam_goal(deadline=date(2026, 7, 10))
    lookup = _FakeLookup(result=date(2026, 8, 2))
    assert await resolve_exam_deadline(goal, today=_TODAY, lookup=lookup) is False
    assert goal["deadline"] == date(2026, 7, 10)
    assert lookup.calls == 0


async def test_past_resolved_date_rejected():
    goal = _exam_goal()
    lookup = _FakeLookup(result=date(2026, 1, 1))  # 과거
    assert await resolve_exam_deadline(goal, today=_TODAY, lookup=lookup) is False
    assert "deadline" not in goal


async def test_lookup_exception_fails_open():
    goal = _exam_goal()
    lookup = _FakeLookup(raises=True)
    assert await resolve_exam_deadline(goal, today=_TODAY, lookup=lookup) is False
    assert "deadline" not in goal  # 예외는 되묻기로 폴백
