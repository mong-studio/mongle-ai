from sft_pipeline.structure.daily_normalize import (
    parse_cadence,
    parse_horizon_days,
    parse_time_of_day,
)


def test_cadence_weekly_count_is_specific():
    assert parse_cadence("주 3회").specific is True


def test_cadence_weekdays_is_specific():
    assert parse_cadence("월수금").specific is True


def test_cadence_daily_is_specific():
    assert parse_cadence("매일").specific is True


def test_cadence_vague_is_not_specific():
    assert parse_cadence("매주").specific is False
    assert parse_cadence("").specific is False


def test_horizon_keyword_and_units():
    assert parse_horizon_days("한 달") == 30
    assert parse_horizon_days("4주") == 28
    assert parse_horizon_days("언젠가") is None
    assert parse_horizon_days(None) is None


def test_time_of_day_maps_known_words():
    assert parse_time_of_day("아침에") == "아침"
    assert parse_time_of_day("저녁 운동") == "저녁"
    assert parse_time_of_day("아무때나") == ""
