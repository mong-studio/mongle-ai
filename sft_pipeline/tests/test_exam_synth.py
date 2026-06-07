import collections
import json
from datetime import date

from sft_pipeline.build.exam_synth import (
    EXAM_TYPES,
    build_seeds,
    synthesize_sample,
    synthesize_to_file,
    to_user_text,
)
from sft_pipeline.build.plan_schemas import check_plan_consistency, parse_plan

TODAY = date(2026, 6, 6)

_SEED = {
    "exam_type": "토익",
    "goal": "900점",
    "days_left": 14,
    "daily_hours": 3,
    "level": "중급",
    "note": "직장 병행",
}


def test_build_seeds_even_per_type_and_deterministic():
    s1 = build_seeds(1000)
    s2 = build_seeds(1000)
    assert s1 == s2  # 결정론적
    counts = collections.Counter(s["exam_type"] for s in s1)
    assert set(counts) == set(EXAM_TYPES)
    vals = list(counts.values())
    assert max(vals) - min(vals) <= 1  # 종류별 균등(±1)
    assert 994 <= len(s1) <= 1000


def test_to_user_text_has_condition_fields():
    u = to_user_text(_SEED, today=TODAY)
    assert "토익" in u
    assert "D-14" in u
    assert "900점" in u
    assert "2026-06-06" in u  # 기준일 앵커


def test_fallback_is_consistent_exam_plan():
    sample = synthesize_sample(_SEED, today=TODAY, client=None)
    meta = sample["meta"]
    assert meta["provenance"] == "exam-synth"
    assert meta["exam_type"] == "토익"
    assert meta["time_left_days"] == 14
    assert meta["today"] == "2026-06-06"
    assert meta["turn_type"] == "single"
    assert meta["synthesized_by"] == "template"
    assert [m["role"] for m in sample["messages"]] == ["user", "assistant"]
    plan = parse_plan(sample["messages"][-1]["content"])
    assert check_plan_consistency(plan, today=TODAY, horizon_days=14) == []


def _fake_client(content: str):
    class _Msg:
        pass

    _Msg.content = content

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _Resp()

    return _Client()


def _plan_payload():
    return json.dumps(
        {
            "summary_text": "기출 회독 후 파트별 약점 보완에 집중하는 전략이에요.",
            "todos": [{"title": "오늘 파트5 집중", "due_date": "2026-06-06", "tags": ["공부"]}],
            "calendar_events": [
                {"title": "기출 1회차 풀이", "due_date": "2026-06-08", "tags": ["공부"]},
                {"title": "오답노트 정리·반복", "due_date": "2026-06-12", "tags": ["공부"]},
            ],
        },
        ensure_ascii=False,
    )


def test_synthesize_uses_llm_client_and_marks_llm():
    sample = synthesize_sample(_SEED, today=TODAY, client=_fake_client(_plan_payload()))
    assert sample["meta"]["synthesized_by"] == "llm"
    plan = parse_plan(sample["messages"][-1]["content"])
    assert plan.calendar_events[0].title == "기출 1회차 풀이"


def test_synthesize_falls_back_on_out_of_horizon_plan():
    bad = _plan_payload().replace("2026-06-12", "2026-08-01")  # D-14 밖
    sample = synthesize_sample(_SEED, today=TODAY, client=_fake_client(bad))
    assert sample["meta"]["synthesized_by"] == "template"


def test_synthesize_to_file_writes_and_counts(tmp_path):
    seeds = build_seeds(12)
    out = tmp_path / "exam_synth.jsonl"
    total, counts = synthesize_to_file(seeds, out, today=TODAY, client=None)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert total == len(seeds)
    assert len(lines) == len(seeds)
    assert counts["template"] == len(seeds)
