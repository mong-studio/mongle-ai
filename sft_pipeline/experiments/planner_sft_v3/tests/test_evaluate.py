import json

from sft_pipeline.experiments.planner_sft_v3.evaluate import passes_gate, score_outputs


def _output(raw_text, scores=None, kind="lifestyle"):
    return {
        "input_id": "x",
        "parsed_goal": {"plan_kind": kind, "goal_text": "목표", "deadline": "2026-07-20",
                        "slots": {"goal": "목표"}},
        "today": "2026-07-05",
        "raw_text": raw_text,
        "judge_scores": scores,
    }


GOOD = json.dumps({"summary_text": "차근차근 진행해요.", "days": [
    {"date": "2026-07-06", "tasks": [{"title": "상태 점검", "due_date": "2026-07-06"}]}
]}, ensure_ascii=False)


def test_score_outputs_all_good():
    metrics = score_outputs([_output(GOOD, {"M1": 4, "M2": 4, "M3": 4, "M4": 4, "average": 4.0})])
    assert metrics["parse_rate"] == 1.0
    assert metrics["structure_violation_rate"] == 0.0
    assert metrics["exam_leak"] == 0
    assert metrics["semantic_avg"] == 4.0


def test_score_outputs_counts_failures():
    bad_parse = _output("JSON 아님")
    leak = _output(json.dumps({"summary_text": "기출 위주로 준비해요.", "days": [
        {"date": "2026-07-06", "tasks": [{"title": "기출 문제 풀이", "due_date": "2026-07-06"}]}
    ]}, ensure_ascii=False), {"M1": 4, "M2": 4, "M3": 4, "M4": 4, "average": 4.0})
    metrics = score_outputs([bad_parse, leak])
    assert metrics["parse_rate"] == 0.5
    assert metrics["exam_leak"] == 1


def test_passes_gate_thresholds():
    ok = {"parse_rate": 0.9, "structure_violation_rate": 0.1, "deadline_rate": 0.8,
          "exam_leak": 0, "english_leak": 0, "semantic_avg": 3.6}
    passed, failures = passes_gate(ok)
    assert passed and failures == []

    bad = dict(ok, exam_leak=1, semantic_avg=3.2)
    passed, failures = passes_gate(bad)
    assert not passed
    assert len(failures) == 2
