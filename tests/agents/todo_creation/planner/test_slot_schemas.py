from agents.todo_creation.planner.slot_schemas import (
    SLOT_SCHEMAS,
    missing_required,
    slot_hints,
)


def test_slot_hints_maps_keys_to_korean_hints() -> None:
    assert slot_hints("routine", ["cadence"]) == ["주 몇 회 또는 어떤 요일인지"]


def test_slot_hints_unknown_key_or_kind_passthrough() -> None:
    assert slot_hints("routine", ["nope"]) == ["nope"]
    assert slot_hints(None, ["deadline"]) == ["deadline"]


def test_all_plan_kinds_present() -> None:
    assert set(SLOT_SCHEMAS) == {
        "exam",
        "event",
        "routine",
        "vague_goal",
        "lifestyle",
        "project",
    }


def test_missing_required_returns_unfilled_required_slots() -> None:
    # routine 필수: activity, cadence
    assert missing_required("routine", {"activity"}) == ["cadence"]


def test_missing_required_empty_when_all_filled() -> None:
    assert missing_required("routine", {"activity", "cadence"}) == []


def test_missing_required_unknown_kind_uses_project_schema() -> None:
    assert missing_required("nonexistent", set()) == [
        "goal",
        "horizon",
        "available_time",
    ]


def test_required_slots_ordered_by_priority() -> None:
    # lifestyle 필수 슬롯이 우선순위 순으로 반환되는지(작은 priority 먼저)
    result = missing_required("lifestyle", set())
    assert result[0] == "domains"  # 가장 높은 우선순위
