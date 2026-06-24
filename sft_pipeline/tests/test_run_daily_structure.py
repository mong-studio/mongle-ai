import csv

from sft_pipeline.structure.run_daily_structure import (
    STRUCTURED_DAILY_COLUMNS,
    write_structured_daily,
)


def test_writes_structured_csv_with_lists_joined(tmp_path):
    rows = [
        {
            "source_url": "https://blog.example.com/1",
            "source_type": "blog",
            "plan_kind": "루틴",
            "goal_text": "꾸준히 운동",
            "activity": "헬스",
            "domains": "운동;학습",
            "cadence": "주 3회",
            "time_of_day": "저녁",
            "horizon": "한 달",
            "trigger": "건강검진",
            "real_breakdown": "주3회 헬스|주3|저녁",
        }
    ]
    out = tmp_path / "structured_daily.csv"
    n = write_structured_daily(rows, out)
    assert n == 1
    with open(out, encoding="utf-8") as f:
        record = next(csv.DictReader(f))
    assert record["plan_kind"] == "routine"
    assert record["domains"] == "운동;학습"
    assert record["horizon_days"] == "30"
    assert set(STRUCTURED_DAILY_COLUMNS).issubset(record.keys())
