import json
from datetime import date

from sft_pipeline.build.lib.daily_nodes_template import (
    build_daily_days,
    build_records,
    is_daily_sufficient,
    parse_real_breakdown,
)

TODAY = date(2026, 6, 24)


def _routine_case(**over):
    base = {
        "source_url": "u",
        "source_type": "blog",
        "plan_kind": "routine",
        "goal_text": "꾸준히 운동",
        "activity": "헬스",
        "domains": "운동",
        "cadence": "주 3회",
        "time_of_day": "저녁",
        "horizon_days": "30",
        "trigger": "건강검진",
        "real_breakdown": "주3회 헬스|주3|저녁;런닝 30분|주2|아침",
    }
    base.update(over)
    return base


def test_routine_with_required_slots_is_sufficient():
    ok, missing = is_daily_sufficient(_routine_case())
    assert ok is True
    assert missing == []


def test_routine_missing_cadence_is_insufficient():
    ok, missing = is_daily_sufficient(_routine_case(cadence=""))
    assert ok is False
    assert "cadence" in missing


def test_parse_real_breakdown_splits_fields():
    items = parse_real_breakdown("주3회 헬스|주3|저녁;런닝 30분|주2|아침")
    assert items[0]["title"] == "주3회 헬스"
    assert items[1]["time_of_day"] == "아침"


def test_build_daily_days_respects_contract():
    days = build_daily_days(_routine_case(), TODAY)
    assert 1 <= len(days) <= 7
    total = sum(len(d["tasks"]) for d in days)
    assert total <= 12
    for d in days:
        assert 1 <= len(d["tasks"]) <= 3
        for t in d["tasks"]:
            assert t["due_date"] == d["date"]
    titles = [t["title"] for d in days for t in d["tasks"]]
    assert not any("점검" in x or "확인" in x or "정리" in x for x in titles)


def test_build_records_sufficient_emits_all_nodes():
    records = build_records(_routine_case(), TODAY)
    nodes = {r["meta"]["node"] for r in records}
    assert {"judge", "goal_tag", "generator", "critic"} <= nodes
    assert all(r["meta"]["provenance"] in ("daily-crawl", "daily-critic") for r in records)


def test_build_records_insufficient_emits_judge_only():
    records = build_records(_routine_case(cadence=""), TODAY)
    judge = [r for r in records if r["meta"]["node"] == "judge"][0]
    assistant = json.loads(judge["messages"][-1]["content"])
    assert assistant["is_sufficient"] is False
    assert "generator" not in {r["meta"]["node"] for r in records}
