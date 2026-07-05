from collections import Counter

from sft_pipeline.experiments.planner_sft_v3.goal_corpus import (
    HOLDOUT_FIXED_GOALS,
    build_inputs,
)


def test_deterministic():
    a_train, a_hold = build_inputs()
    b_train, b_hold = build_inputs()
    assert a_train == b_train and a_hold == b_hold


def test_counts_and_distribution():
    train, hold = build_inputs()
    assert len(train) == 960 - 25  # holdout 25건은 train에서 제외
    assert len(hold) == 30
    dist = Counter(i["domain"] for i in train)
    # lifestyle 40% / routine·exam·범용(project+event) 각 20% (holdout 제외 오차 허용)
    total = sum(dist.values())
    assert abs(dist["lifestyle"] / total - 0.40) < 0.03
    assert abs(dist["routine"] / total - 0.20) < 0.03
    assert abs(dist["exam"] / total - 0.20) < 0.03
    assert abs((dist["project"] + dist["event"]) / total - 0.20) < 0.03


def test_holdout_contains_v2_readme_probes_and_no_overlap():
    train, hold = build_inputs()
    hold_goals = {h["parsed_goal"]["goal_text"] for h in hold}
    for probe in HOLDOUT_FIXED_GOALS:
        assert probe in hold_goals
    train_ids = {t["input_id"] for t in train}
    assert not train_ids & {h["input_id"] for h in hold}


def test_parsed_goal_shape():
    train, _ = build_inputs()
    goal = train[0]["parsed_goal"]
    for key in ("intent", "plan_kind", "slots", "goal_text", "goal_tag",
                "deadline", "daily_capacity_minutes", "personalization_patch"):
        assert key in goal, key
