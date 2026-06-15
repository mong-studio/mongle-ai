from datetime import date

from adapters.todo_creation.date_extract import extract_exam_dates


def test_extracts_iso_exam_date() -> None:
    out = extract_exam_dates("정보처리기사 필기 시험일은 2026-07-05입니다", today=date(2026, 6, 1))
    assert len(out) == 1
    assert out[0].date == date(2026, 7, 5)
    assert out[0].part == "필기"


def test_excludes_registration_date() -> None:
    out = extract_exam_dates("원서접수 2026-06-10, 필기시험 2026-07-05", today=date(2026, 6, 1))
    dates = [c.date for c in out]
    assert date(2026, 6, 10) not in dates  # 접수일 제외
    assert date(2026, 7, 5) in dates


def test_drops_past_dates() -> None:
    assert extract_exam_dates("필기 7월 5일", today=date(2026, 8, 1)) == []


def test_separates_written_and_practical() -> None:
    out = extract_exam_dates("필기 7월 5일, 실기 8월 17일", today=date(2026, 6, 1))
    parts = {c.part: c.date for c in out}
    assert parts["필기"] == date(2026, 7, 5)
    assert parts["실기"] == date(2026, 8, 17)


def test_dedups_full_and_md_forms() -> None:
    out = extract_exam_dates("필기 2026년 7월 5일(7월 5일) 시험", today=date(2026, 6, 1))
    assert [c.date for c in out] == [date(2026, 7, 5)]


def test_full_date_other_year_does_not_spawn_today_year_ghost() -> None:
    # "2027년 7월 5일" 의 'M월 D일' 부분이 today.year(2026) 로 재해석되어
    # 유령 날짜 2026-07-05 를 만들면 안 된다(연도 불일치 → dedup 도 못 거름).
    out = extract_exam_dates("필기 시험 2027년 7월 5일", today=date(2026, 6, 1))
    assert [c.date for c in out] == [date(2027, 7, 5)]
