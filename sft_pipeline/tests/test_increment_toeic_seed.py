"""토익 골드 시드 빌더 검증.

increment_exam_seed(정보처리기사)와 같은 방법으로 생성한 `{messages, meta}` 시드가
런타임 플래너 스키마(kind/title/phases/tasks)와 날짜 정합성(today<=due<=deadline),
제목 길이(20자), 그리고 공식 시험 사실(990점·LC/RC·200문항)을 만족하는지 본다.
"""
import json
from datetime import date

from sft_pipeline.build.jobs.increment_exam_seed import _load_json
from sft_pipeline.build.jobs.increment_toeic_seed import (
    DEFAULT_INFO_PATH,
    VALID_PARTS,
    _make_plan_case,
    build_samples,
)

TODAY = date(2026, 6, 14)
INFO = _load_json(DEFAULT_INFO_PATH)


def _assistant(sample: dict) -> dict:
    return json.loads(sample["messages"][-1]["content"])


def test_info_file_has_required_shape():
    assert INFO["exam_code"] == "toeic"
    assert INFO["exam_format"]["max_score"] == 990
    assert set(INFO["exam_parts"]) == {"listening", "reading"}
    assert INFO["review_patterns"], "review_patterns 비어있음"


def test_build_samples_is_deterministic_and_has_followup():
    s1 = build_samples(INFO, TODAY)
    s2 = build_samples(INFO, TODAY)
    assert s1 == s2  # 결정론적
    kinds = [s["meta"]["kind"] for s in s1]
    assert "follow_up" in kinds
    assert kinds.count("plan") == len(INFO["review_patterns"])
    ids = [s["meta"]["id"] for s in s1]
    assert len(ids) == len(set(ids)), "meta.id 중복"


def test_followup_case_shape():
    followup = build_samples(INFO, TODAY)[0]
    assert [m["role"] for m in followup["messages"]] == ["system", "user", "assistant"]
    body = _assistant(followup)
    assert body["kind"] == "follow_up"
    assert body["question"].strip()
    assert isinstance(body["missing_aspects"], list) and body["missing_aspects"]


def _plan_samples():
    return [s for s in build_samples(INFO, TODAY) if s["meta"]["kind"] == "plan"]


def test_plan_cases_have_runtime_planner_shape():
    for sample in _plan_samples():
        assert [m["role"] for m in sample["messages"]] == ["system", "user", "assistant"]
        plan = _assistant(sample)
        assert plan["kind"] == "plan"
        assert plan["title"].strip() and len(plan["title"]) <= 30
        assert plan["summary_text"].strip()
        assert isinstance(plan["phases"], list) and plan["phases"]
        for phase in plan["phases"]:
            assert phase["phase"].strip()
            assert isinstance(phase["tasks"], list) and phase["tasks"]
            for task in phase["tasks"]:
                assert task["title"].strip() and len(task["title"]) <= 20
                assert task["priority"] in {"high", "medium", "low"}
                assert isinstance(task["tags"], list)


def test_plan_dates_within_today_and_deadline():
    for sample in _plan_samples():
        plan = _assistant(sample)
        deadline = date.fromisoformat(plan["deadline"])
        assert deadline >= TODAY
        for phase in plan["phases"]:
            assert TODAY <= date.fromisoformat(phase["due_date"]) <= deadline
            for task in phase["tasks"]:
                assert TODAY <= date.fromisoformat(task["due_date"]) <= deadline
        for event in plan["calendar_events"]:
            assert TODAY <= date.fromisoformat(event["due_date"]) <= deadline


def test_plan_summaries_carry_official_toeic_facts():
    for sample in _plan_samples():
        summary = _assistant(sample)["summary_text"]
        assert "990" in summary
        assert "200문항" in summary
        assert "LC" in summary and "RC" in summary


def test_meta_parts_are_valid_and_sourced():
    for sample in _plan_samples():
        meta = sample["meta"]
        assert meta["exam_code"] == "toeic"
        assert meta["domain"] == "exam"
        assert meta["exam_part"] in VALID_PARTS
        assert meta["today"] == "2026-06-14"
        assert all(u.startswith("http") for u in meta["official_sources"])
        assert meta["study_process_summary"].strip()


def test_unknown_part_raises():
    bad = {**INFO["review_patterns"][0], "part": "speaking", "case_id": "x"}
    try:
        _make_plan_case(INFO, bad, TODAY)
    except ValueError as exc:
        assert "speaking" in str(exc)
    else:
        raise AssertionError("unknown part should raise ValueError")
