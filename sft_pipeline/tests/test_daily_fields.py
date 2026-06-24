from sft_pipeline.structure.daily_fields import structure_daily_row


def _row(**over):
    base = {
        "source_url": "https://blog.example.com/1",
        "source_type": "blog",
        "plan_kind": "루틴",
        "goal_text": "꾸준히 운동",
        "activity": "헬스",
        "domains": "운동",
        "cadence": "주 3회",
        "time_of_day": "저녁",
        "horizon": "한 달",
        "trigger": "건강검진 경고",
        "real_breakdown": "주3회 헬스|주3|저녁",
    }
    base.update(over)
    return base


def test_maps_plan_kind_and_domains():
    case = structure_daily_row(_row())
    assert case.plan_kind == "routine"
    assert case.domains == ["운동"]
    assert case.cadence_specific is True
    assert case.horizon_days == 30
    assert case.review_flags == []


def test_unmapped_plan_kind_flags_and_blanks():
    case = structure_daily_row(_row(plan_kind="기상천외"))
    assert case.plan_kind == ""
    assert "plan_kind_unmapped" in case.review_flags


def test_vague_cadence_flagged():
    case = structure_daily_row(_row(cadence="매주"))
    assert case.cadence_specific is False
    assert "cadence_vague" in case.review_flags


def test_missing_real_breakdown_flagged():
    case = structure_daily_row(_row(real_breakdown=""))
    assert "real_breakdown_missing" in case.review_flags


def test_unknown_domain_dropped_and_flagged():
    case = structure_daily_row(_row(domains="운동;우주여행"))
    assert case.domains == ["운동"]
    assert "domain_unmapped" in case.review_flags
