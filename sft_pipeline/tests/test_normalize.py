from sft_pipeline.structure.normalize import parse_time_left, parse_daily_hours


def test_time_left_d_minus():
    """'D-7' 형식의 남은 기간을 일수로 파싱하는지 확인."""
    assert parse_time_left("D-7").days == 7


def test_time_left_korean_keywords():
    """'일주일'·'한 달' 같은 한국어 표현을 일수로 변환하는지 확인."""
    assert parse_time_left("일주일").days == 7
    assert parse_time_left("한 달").days == 30


def test_time_left_number_unit():
    """'2주'·'10일 남음' 같은 숫자+단위 표현을 일수로 파싱하는지 확인."""
    assert parse_time_left("2주").days == 14
    assert parse_time_left("10일 남음").days == 10
    assert parse_time_left("2주일").days == 14


def test_time_left_missing_returns_none():
    """기간 미기재·빈 문자열이면 days가 None인지 확인."""
    assert parse_time_left("미기재").days is None
    assert parse_time_left("").days is None


def test_daily_hours_single():
    """'하루 4시간' 단일 값은 hours=4, 범위(min)는 없는지 확인."""
    dh = parse_daily_hours("하루 4시간")
    assert dh.hours == 4.0 and dh.hours_min is None


def test_daily_hours_range():
    """'3~5시간' 범위는 min/max와 중앙값(hours)을 계산하는지 확인."""
    dh = parse_daily_hours("3~5시간")
    assert dh.hours_min == 3.0 and dh.hours_max == 5.0 and dh.hours == 4.0


def test_daily_hours_minutes():
    """'30분' 분 단위를 시간(0.5)으로 환산하는지 확인."""
    assert parse_daily_hours("30분").hours == 0.5


def test_daily_hours_missing():
    """학습시간 빈 문자열이면 hours가 None인지 확인."""
    assert parse_daily_hours("").hours is None
