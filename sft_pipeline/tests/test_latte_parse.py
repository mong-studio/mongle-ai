from sft_pipeline.latte.parse import (
    aggregate_location,
    aggregate_time,
    parse_record,
)


def test_aggregate_location_majority_home():
    """다수결 broad 위치가 home으로, Known 다수가 yes면 loc_known=True."""
    judgements = [
        {"Known": "yes", "Locations": "home", "PublicLocations": ""},
        {"Known": "yes", "Locations": "home", "PublicLocations": ""},
        {"Known": "yes", "Locations": "work", "PublicLocations": ""},
    ]
    loc = aggregate_location(judgements)
    assert loc["known"] is True
    assert loc["broad"] == "home"
    assert loc["public"] == ""


def test_aggregate_location_public_finegrained():
    """broad가 public이면 PublicLocations의 다수결 세부 장소를 채운다."""
    judgements = [
        {"Known": "yes", "Locations": "public", "PublicLocations": "gym"},
        {"Known": "yes", "Locations": "public", "PublicLocations": "gym"},
        {"Known": "yes", "Locations": "home", "PublicLocations": ""},
    ]
    loc = aggregate_location(judgements)
    assert loc["broad"] == "public"
    assert loc["public"] == "gym"


def test_aggregate_location_unknown_when_majority_no():
    """Known 다수가 no면 loc_known=False."""
    judgements = [
        {"Known": "no", "Locations": "", "PublicLocations": ""},
        {"Known": "no", "Locations": "", "PublicLocations": ""},
        {"Known": "yes", "Locations": "home", "PublicLocations": ""},
    ]
    assert aggregate_location(judgements)["known"] is False


def test_aggregate_time_keeps_agreed_slots():
    """콤마구분 시간코드를 펼쳐 집계하고, 2명 이상 동의한 슬롯만 남긴다."""
    judgements = [
        {"Known": "yes", "Times": "WE-morning"},
        {"Known": "yes", "Times": "WE-morning"},
        {"Known": "yes", "Times": "WE-afternoon,WD-evening"},
        {"Known": "yes", "Times": "WE-morning"},
        {"Known": "yes", "Times": "WE-evening"},
    ]
    time = aggregate_time(judgements)
    assert time["known"] is True
    assert time["top_times"] == ["WE-morning"]


def test_aggregate_time_falls_back_to_top_one():
    """2명 이상 동의 슬롯이 없으면 최빈 1개로 폴백한다."""
    judgements = [
        {"Known": "yes", "Times": "WE-morning"},
        {"Known": "yes", "Times": "WD-evening"},
    ]
    assert aggregate_time(judgements)["top_times"] == ["WD-evening"]


def test_parse_record_full_shape():
    """레코드 → 시드 dict 전체 형태."""
    rec = {
        "ID": "3026964",
        "TaskTitle": "rearrange closet",
        "ListTitle": "home",
        "LocJudgements": [
            {"Known": "yes", "Locations": "home", "PublicLocations": ""},
            {"Known": "yes", "Locations": "home", "PublicLocations": ""},
        ],
        "TimeJudgements": [
            {"Known": "yes", "Times": "WE-morning"},
            {"Known": "yes", "Times": "WE-morning"},
        ],
    }
    seed = parse_record(rec)
    assert seed["id"] == "3026964"
    assert seed["task_title"] == "rearrange closet"
    assert seed["list_title"] == "home"
    assert seed["broad_location"] == "home"
    assert seed["top_times"] == ["WE-morning"]
