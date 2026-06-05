from sft_pipeline.latte.localize import (
    decode_time,
    localize_broad,
    localize_place,
    localize_public,
    localize_seed,
)


def test_decode_time_weekday_weekend():
    assert decode_time("WE-morning") == "주말 아침"
    assert decode_time("WD-evening") == "평일 저녁"
    assert decode_time("WE-anytime") == "주말 아무때나"
    assert decode_time("WD-night") == "평일 밤"


def test_decode_time_unknown_passthrough():
    """매핑 못 하는 코드는 빈 문자열로(하류에서 걸러짐)."""
    assert decode_time("ZZ-foo") == ""


def test_localize_broad_simple_and_compound():
    assert localize_broad("home") == "집"
    assert localize_broad("work") == "회사"
    assert localize_broad("public") == "외부"
    assert localize_broad("home,work") == "집/회사"


def test_localize_public_maps_and_dedups_compound():
    assert localize_public("grocery") == "마트"
    assert localize_public("pharmacy") == "약국"
    # doctor와 hospital 둘 다 '병원' → 중복 제거
    assert localize_public("doctor,hospital") == "병원"


def test_localize_place_prefers_public_detail():
    """세부 public이 있으면 그걸, 없으면 broad 라벨을 장소로 쓴다."""
    assert localize_place("public", "grocery") == "마트"
    assert localize_place("home", "") == "집"


def test_localize_seed_full_shape():
    seed = {
        "id": "1",
        "task_title": "buy milk",
        "broad_location": "public",
        "public_location": "grocery",
        "top_times": ["WE-morning", "WD-evening"],
    }
    out = localize_seed(seed)
    assert out["id"] == "1"
    assert out["task_title"] == "buy milk"
    assert out["broad_ko"] == "외부"
    assert out["place_ko"] == "마트"
    assert out["times_ko"] == ["주말 아침", "평일 저녁"]


def test_localize_seed_filters_unsynthesizable():
    """장소나 시간이 비면 합성 불가 → None 반환."""
    assert localize_seed({"id": "2", "task_title": "x", "broad_location": "", "public_location": "", "top_times": []}) is None
    assert localize_seed({"id": "3", "task_title": "x", "broad_location": "home", "public_location": "", "top_times": []}) is None
