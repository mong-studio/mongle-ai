from sft_pipeline.structure.daily_taxonomy import (
    canonicalize_domain,
    canonicalize_plan_kind,
)


def test_plan_kind_alias_maps_to_canonical():
    assert canonicalize_plan_kind("루틴") == "routine"
    assert canonicalize_plan_kind("라이프스타일") == "lifestyle"


def test_plan_kind_normalizes_spaces_and_case():
    assert canonicalize_plan_kind(" 막연한 목표 ") == "vague_goal"


def test_unknown_plan_kind_returns_none():
    assert canonicalize_plan_kind("기상천외") is None
    assert canonicalize_plan_kind("") is None
    assert canonicalize_plan_kind(None) is None


def test_domain_alias_maps_to_canonical():
    assert canonicalize_domain("헬스") == "운동"
    assert canonicalize_domain("영어") == "학습"


def test_unknown_domain_returns_none():
    assert canonicalize_domain("우주여행") is None
