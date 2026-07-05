import pytest

from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
    SEMANTIC_JUDGE_SYSTEM,
    parse_judge_reply,
    semantic_judge_user,
    verdict,
)


def test_judge_prompt_mentions_all_dimensions():
    for token in ("M1", "M2", "M3", "M4", "1~5", "JSON"):
        assert token in SEMANTIC_JUDGE_SYSTEM


def test_judge_user_contains_goal_and_plan():
    text = semantic_judge_user(
        {"summary_text": "요약", "days": []},
        {"goal_text": "운동과 독서 병행", "plan_kind": "lifestyle"},
    )
    assert "운동과 독서 병행" in text and "요약" in text


def test_parse_judge_reply():
    reply = '{"M1": 4, "M2": 5, "M3": 4, "M4": 3}'
    scores = parse_judge_reply(reply)
    assert scores["average"] == 4.0


def test_parse_judge_reply_rejects_out_of_range():
    with pytest.raises(ValueError):
        parse_judge_reply('{"M1": 9, "M2": 1, "M3": 1, "M4": 1}')
    with pytest.raises(ValueError):
        parse_judge_reply("좋은 계획이네요")


def test_verdict_rules():
    assert verdict(False, [], None) == "DROP"            # 구문 FAIL
    assert verdict(True, ["S2: ..."], 5.0) == "DROP"      # 구조 FAIL 은 점수로 희석 금지
    assert verdict(True, [], 2.9) == "DROP"
    assert verdict(True, [], 3.5) == "FIX"
    assert verdict(True, [], 4.0) == "ACCEPT"
