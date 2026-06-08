import json

from sft_pipeline.build.coherence_eval import eval_dataset


def _plan_content(events_due="2026-06-10", mechanical=False):
    if mechanical:
        events = [
            {"title": f"{i}단원 풀기", "due_date": events_due, "tags": ["공부"]} for i in range(1, 4)
        ]
    else:
        events = [{"title": "기출 풀이와 오답 점검", "due_date": events_due, "tags": ["공부"]}]
    return json.dumps(
        {
            "summary_text": "기출 회독 후 약점 보완 전략이에요.",
            "todos": [{"title": "핵심 개념 훑기", "due_date": "2026-06-06", "tags": ["공부"]}],
            "calendar_events": events,
        },
        ensure_ascii=False,
    )


def _exam_synth(content=None):
    return {
        "messages": [
            {"role": "user", "content": "시험: 토익 / D-14 / 기준일(오늘): 2026-06-06"},
            {"role": "assistant", "content": content if content is not None else _plan_content()},
        ],
        "meta": {"provenance": "exam-synth", "task_type": "plan", "exam_type": "토익", "time_left_days": 14, "today": "2026-06-06"},
    }


def _distractor(content="도움이 됐다면 다행이야. 더 말해줘."):
    return {
        "messages": [
            {"role": "user", "content": "고마워"},
            {"role": "assistant", "content": content},
        ],
        "meta": {"provenance": "distractor", "task_type": "chat", "distractor_type": "thanks_chitchat"},
    }


def _has_rationale(node):
    return isinstance(node, dict) and isinstance(node.get("rationale"), str) and node["rationale"]


def test_counts_and_provenance():
    r = eval_dataset([_exam_synth(), _distractor()])
    assert r["n_samples"] == 2
    assert r["by_provenance"] == {"exam-synth": 1, "distractor": 1}


def test_exact_duplicate_detected_with_rationale():
    g = _exam_synth()
    r = eval_dataset([g, dict(g), _distractor()])  # 동일 plan 2개
    dup = r["quantitative"]["exact_duplicate_rate"]
    assert dup["count"] == 1
    assert _has_rationale(dup)


def test_gate1_syntax_fail_on_bad_json():
    bad = _exam_synth(content="이건 JSON이 아니에요")
    r = eval_dataset([_exam_synth(), bad])
    g1 = r["quantitative"]["plan"]["gate1_syntax_pass_rate"]
    assert g1["value"] == 0.5
    assert _has_rationale(g1)


def test_gate2_time_logic_violation_out_of_horizon():
    bad = _exam_synth(content=_plan_content(events_due="2026-08-01"))  # D-14 밖
    r = eval_dataset([bad])
    s2 = r["quantitative"]["plan"]["gate2_S2_time_logic_violation_rate"]
    assert s2["value"] == 1.0
    assert _has_rationale(s2)


def test_gate3_mechanical_decomposition_rate():
    mech = _exam_synth(content=_plan_content(mechanical=True))
    r = eval_dataset([_exam_synth(), mech])
    m1 = r["quantitative"]["plan"]["gate3_M1_mechanical_rate"]
    assert m1["value"] == 0.5
    assert _has_rationale(m1)


def test_distractor_leak_flagged():
    leak = _distractor(content=_plan_content())  # distractor인데 플랜 JSON 출력 = 누수
    r = eval_dataset([_distractor(), leak])
    lk = r["quantitative"]["distractor"]["leak_rate"]
    assert lk["count"] == 1
    assert _has_rationale(lk)


def test_qualitative_rubric_present():
    r = eval_dataset([_exam_synth()])
    q = r["qualitative"]
    assert set(["M1", "M2", "M3", "M4"]).issubset(q["rubric"].keys())
    assert q["samples_for_review"]  # 정성 채점용 샘플 포함
