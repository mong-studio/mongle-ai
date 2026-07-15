from llm_evaluation.langsmith.evaluators import (
    structure_valid, routing_correct, date_sanity, korean_only, frontend_contract,
    plan_density,
)

_TODAY = "2026-07-15"


def _plan_out(todos):
    return {"kind": "candidates", "result": {
        "kind": "candidates", "thread_id": "t", "todos": todos,
        "calendar_events": [], "summary_text": "요약", "personalization_patch": None}}


def _todo(title="공부", due="2026-07-20", tags=None):
    return {"title": title, "due_date": due, "tags": tags or ["학습"]}


def _inputs(turns=None):
    return {"user_id": "u1", "turns": turns or ["수능 공부 계획"], "today": _TODAY,
            "user_profile_memory": None}


def test_structure_valid_pass():
    out = _plan_out([_todo()])
    assert structure_valid(out, {"expected_kind": "candidates"}, _inputs())["score"] == 1


def test_structure_valid_fail_bad_title():
    out = _plan_out([_todo(title="")])  # min_length=1 위반
    assert structure_valid(out, {"expected_kind": "candidates"}, _inputs())["score"] == 0


def test_routing_correct():
    out = {"kind": "follow_up", "result": {"kind": "follow_up", "thread_id": "t",
           "question": "언제까지?", "missing_aspects": ["deadline"]}}
    assert routing_correct(out, {"expected_kind": "follow_up"}, _inputs())["score"] == 1
    assert routing_correct(out, {"expected_kind": "candidates"}, _inputs())["score"] == 0


def test_date_sanity_past_due_fails():
    out = _plan_out([_todo(due="2026-07-01")])  # today 이전
    assert date_sanity(out, {}, _inputs())["score"] == 0
    out2 = _plan_out([_todo(due="2026-07-20")])
    assert date_sanity(out2, {}, _inputs())["score"] == 1


def test_korean_only_flags_foreign():
    out = _plan_out([_todo(title="勉強する")])  # 일본어/한자
    assert korean_only(out, {}, _inputs())["score"] == 0
    assert korean_only(_plan_out([_todo(title="공부하기")]), {}, _inputs())["score"] == 1


def test_frontend_contract_requires_render_fields():
    good = _plan_out([_todo()])
    assert frontend_contract(good, {}, _inputs())["score"] == 1
    bad = {"kind": "candidates", "result": {"kind": "candidates", "thread_id": "t"}}
    assert frontend_contract(bad, {}, _inputs())["score"] == 0


def test_plan_density_sparse_scores_low():
    # 1개 항목, 마감 10일 뒤(horizon 11) → expected=ceil(11/3)=4 → 1/4=0.25
    out = _plan_out([_todo(due="2026-07-25")])
    assert plan_density(out, {}, _inputs())["score"] < 1.0


def test_plan_density_dense_scores_full():
    items = [_todo(due=d) for d in
             ("2026-07-16", "2026-07-18", "2026-07-20", "2026-07-22", "2026-07-25")]
    assert plan_density(_plan_out(items), {}, _inputs())["score"] == 1.0


def test_plan_density_empty_is_zero():
    assert plan_density(_plan_out([]), {}, _inputs())["score"] == 0.0


def test_plan_density_na_for_non_candidates():
    out = {"kind": "follow_up", "result": {"kind": "follow_up"}}
    assert plan_density(out, {}, _inputs())["score"] is None
