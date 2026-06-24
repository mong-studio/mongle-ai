import json
from datetime import date

from sft_pipeline.build.lib.build_daily_followup_sft import build_multiturn_record

TODAY = date(2026, 6, 24)


def _case():
    return {
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
        "real_breakdown": "주3회 헬스|주3|저녁",
    }


def test_single_judge_record_with_history_embedded():
    record = build_multiturn_record(_case(), withheld=["cadence"], today=TODAY)
    roles = [m["role"] for m in record["messages"]]
    # 단일 judge 레코드: 직전 Q&A 는 user content 안 history 에 내재(별도 메시지 아님)
    assert roles == ["system", "user", "assistant"]
    user_content = record["messages"][1]["content"]
    # 질문(? 로 끝남)과 답변이 user content 의 history 에 들어 있다
    assert "?" in user_content
    assert "주 3회" in user_content  # 사용자 답변(원래 cadence 값)
    last = json.loads(record["messages"][-1]["content"])
    assert last["is_sufficient"] is True
    assert record["meta"]["turn_type"] == "multi"
    assert record["meta"]["provenance"] == "daily-crawl"
    assert record["meta"]["missing_aspects"] == ["cadence"]


def test_followup_capped_at_two_aspects():
    record = build_multiturn_record(_case(), withheld=["activity", "cadence", "goal"], today=TODAY)
    assert len(record["meta"]["missing_aspects"]) <= 2


def test_build_samples_reads_structured(tmp_path):
    from sft_pipeline.structure.run_daily_structure import write_structured_daily
    from sft_pipeline.build.lib.build_daily_followup_sft import build_samples
    write_structured_daily([{
        "source_url": "u", "source_type": "blog", "plan_kind": "루틴",
        "goal_text": "꾸준히 운동", "activity": "헬스", "domains": "운동",
        "cadence": "주 3회", "time_of_day": "저녁", "horizon": "한 달",
        "trigger": "건강검진", "real_breakdown": "주3회 헬스|주3|저녁",
    }], tmp_path / "s.csv")
    samples = build_samples(tmp_path / "s.csv", TODAY)
    assert len(samples) >= 1
    assert samples[0]["meta"]["turn_type"] == "multi"
