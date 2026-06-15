from agents.todo_creation.state import ParsedGoal


def test_parsed_goal_accepts_plan_kind_and_slots() -> None:
    goal: ParsedGoal = {
        "intent": "plan",
        "plan_kind": "routine",
        "slots": {"activity": "헬스", "cadence": "주3"},
    }
    assert goal["plan_kind"] == "routine"
    assert goal["slots"]["activity"] == "헬스"
