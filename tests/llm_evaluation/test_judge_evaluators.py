import pytest
from llm_evaluation.langsmith.evaluators import (
    make_judge_evaluators,
    make_plan_quality_evaluator,
)


class _FakeQualityJudge:
    def __init__(self, raw):
        self._raw = raw

    async def complete_raw(self, *, messages, label=None, guided_json=None):
        return self._raw


def _candidates():
    return {"kind": "candidates", "result": {
        "kind": "candidates", "todos": [],
        "calendar_events": [{"due_date": "2026-07-18", "title": "x"}],
        "summary_text": "s"}}


@pytest.mark.asyncio
async def test_plan_quality_normalizes_scores():
    ev = make_plan_quality_evaluator(_FakeQualityJudge('{"m1": 5, "m3": 5, "m4": 5}'))
    r = await ev(_candidates(), {}, {"turns": ["시험 준비"], "today": "2026-07-15"})
    assert r["score"] == 1.0  # (5-1)/4


@pytest.mark.asyncio
async def test_plan_quality_mid_score():
    ev = make_plan_quality_evaluator(_FakeQualityJudge('{"m1": 3, "m3": 3, "m4": 3}'))
    r = await ev(_candidates(), {}, {"turns": ["x"], "today": "2026-07-15"})
    assert r["score"] == 0.5  # (3-1)/4


@pytest.mark.asyncio
async def test_plan_quality_na_for_non_candidates():
    ev = make_plan_quality_evaluator(_FakeQualityJudge('{"m1": 5, "m3": 5, "m4": 5}'))
    r = await ev({"kind": "follow_up", "result": {}}, {}, {"turns": ["x"], "today": "2026-07-15"})
    assert r["score"] is None


@pytest.mark.asyncio
async def test_plan_quality_parse_fail_returns_none():
    ev = make_plan_quality_evaluator(_FakeQualityJudge("not json"))
    r = await ev(_candidates(), {}, {"turns": ["x"], "today": "2026-07-15"})
    assert r["score"] is None and "parse" in r["comment"]


class _FakeJudge:
    def __init__(self, sufficient, missing):
        self._sufficient, self._missing = sufficient, missing
        self.calls = []

    async def judge_sufficiency(self, *, history, message, today, user_profile_memory=None):
        self.calls.append({"history": history, "message": message})
        return self._sufficient, self._missing, {"goal_tag": "목표"}


def _inputs(turns):
    return {"user_id": "u1", "turns": turns, "today": "2026-07-15", "user_profile_memory": None}


def _by_key(evals, key):
    return next(e for e in evals if e.__name__ == key)


@pytest.mark.asyncio
async def test_plan_justified_scores_sufficient():
    judge = _FakeJudge(sufficient=True, missing=[])
    evals = make_judge_evaluators(judge)
    out = {"kind": "candidates", "result": {"kind": "candidates"}}
    res = await _by_key(evals, "plan_justified")(out, {}, _inputs(["A", "B"]))
    assert res["score"] == 1
    # 마지막 턴이 message, 앞 턴이 history
    assert judge.calls[-1]["message"] == "B"


@pytest.mark.asyncio
async def test_plan_justified_na_for_followup():
    judge = _FakeJudge(sufficient=True, missing=[])
    evals = make_judge_evaluators(judge)
    out = {"kind": "follow_up", "result": {"kind": "follow_up"}}
    res = await _by_key(evals, "plan_justified")(out, {}, _inputs(["A"]))
    assert res["score"] is None


@pytest.mark.asyncio
async def test_followup_needed_when_judge_agrees_insufficient():
    judge = _FakeJudge(sufficient=False, missing=["deadline"])
    evals = make_judge_evaluators(judge)
    out = {"kind": "follow_up", "result": {"kind": "follow_up"}}
    res = await _by_key(evals, "followup_needed")(out, {}, _inputs(["시험 공부"]))
    assert res["score"] == 1


@pytest.mark.asyncio
async def test_followup_inappropriate_when_judge_says_sufficient():
    judge = _FakeJudge(sufficient=True, missing=[])
    evals = make_judge_evaluators(judge)
    out = {"kind": "follow_up", "result": {"kind": "follow_up"}}
    res = await _by_key(evals, "followup_needed")(out, {}, _inputs(["11월 3일 정보처리기사"]))
    assert res["score"] == 0
