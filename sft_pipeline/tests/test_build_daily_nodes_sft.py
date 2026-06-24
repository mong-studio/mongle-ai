from datetime import date

from sft_pipeline.build.lib.build_daily_nodes_sft import build_samples
from sft_pipeline.structure.run_daily_structure import write_structured_daily


def test_build_samples_from_structured(tmp_path):
    raw = [{
        "source_url": "u", "source_type": "blog", "plan_kind": "루틴",
        "goal_text": "꾸준히 운동", "activity": "헬스", "domains": "운동",
        "cadence": "주 3회", "time_of_day": "저녁", "horizon": "한 달",
        "trigger": "건강검진", "real_breakdown": "주3회 헬스|주3|저녁",
    }]
    structured = tmp_path / "structured_daily.csv"
    write_structured_daily(raw, structured)
    samples = build_samples(structured, today=date(2026, 6, 24))
    assert len(samples) >= 4  # judge+goal_tag+generator+critic(3)
    assert all("messages" in s and "meta" in s for s in samples)
    assert {"judge", "goal_tag", "generator", "critic"} <= {s["meta"]["node"] for s in samples}
