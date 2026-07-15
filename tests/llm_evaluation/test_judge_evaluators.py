import pytest
from llm_evaluation.langsmith.evaluators import make_judge_evaluators


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
