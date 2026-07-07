import json

from sft_pipeline.experiments.planner_sft_v3.distill_dataset import run_distill
from sft_pipeline.experiments.planner_sft_v3.goal_corpus import build_inputs

GOOD_PLAN_TEMPLATE = json.dumps({
    "summary_text": "무리하지 않게 준비, 실행, 점검 순서로 진행해요.",
    "days": [
        {"date": "{d0}", "tasks": [{"title": "현재 상태 점검", "due_date": "{d0}"}]},
        {"date": "{d1}", "tasks": [{"title": "핵심 연습 시작", "due_date": "{d1}"}]},
    ],
}, ensure_ascii=False)


def _plan_for(sample):
    d0 = sample["today"]
    d1 = sample["parsed_goal"]["deadline"]
    return GOOD_PLAN_TEMPLATE.replace("{d0}", d0).replace("{d1}", d1)


def _fake_judge_accept(system: str, user: str) -> str:
    return '{"M1": 4, "M2": 4, "M3": 5, "M4": 4}'


def _fake_judge_fixband(system: str, user: str) -> str:
    return '{"M1": 3, "M2": 3, "M3": 4, "M4": 4}'  # 평균 3.5 → FIX


def _lifestyle_sample():
    train, _ = build_inputs()
    return next(s for s in train if s["domain"] == "lifestyle")


def test_accepts_good_sample(tmp_path):
    sample = _lifestyle_sample()
    plan = _plan_for(sample)
    result = run_distill([sample], lambda s, u: plan, _fake_judge_accept, tmp_path)
    assert result["report"]["accepted"] == 1
    record = result["accepted"][0]
    assert record["messages"][2]["content"] == plan  # assistant == teacher 원문
    assert record["meta"]["provenance"] == "planner-sft-v3-distill"


def test_fix_band_retries_once_then_drops(tmp_path):
    sample = _lifestyle_sample()
    plan = _plan_for(sample)
    calls = {"n": 0}

    def counting_complete(s, u):
        calls["n"] += 1
        return plan

    result = run_distill([sample], counting_complete, _fake_judge_fixband, tmp_path)
    assert calls["n"] == 2  # FIX → 재생성 1회
    assert result["report"]["accepted"] == 0
    assert result["report"]["dropped"] == 1


def test_structure_violation_drops_with_reason(tmp_path):
    sample = _lifestyle_sample()
    bad = json.dumps({"summary_text": "요약", "days": [
        {"date": "2030-01-01", "tasks": [{"title": "기출 문제 풀이", "due_date": "2030-01-01"}]}
    ]}, ensure_ascii=False)
    result = run_distill([sample], lambda s, u: bad, _fake_judge_accept, tmp_path)
    assert result["report"]["accepted"] == 0
    assert any("S2" in reason for reason in result["report"]["drop_reasons"])


def test_resume_cache_skips_completed(tmp_path):
    sample = _lifestyle_sample()
    plan = _plan_for(sample)
    run_distill([sample], lambda s, u: plan, _fake_judge_accept, tmp_path)

    def boom(s, u):
        raise AssertionError("캐시 히트면 teacher 재호출 금지")

    result = run_distill([sample], boom, _fake_judge_accept, tmp_path)
    assert result["report"]["accepted"] == 1
