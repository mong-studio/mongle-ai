from __future__ import annotations

from agents.character_creation.schemas import CharacterCreationInput
from agents.character_creation.state import CharacterGraphState


def _input() -> CharacterCreationInput:
    return CharacterCreationInput(user_id="u1", name="몽글이", persona="다정한 곰")


def test_state_initial_has_only_required_fields() -> None:
    state: CharacterGraphState = {"input": _input()}
    assert state["input"].user_id == "u1"
    assert state.get("llm_result") is None
    assert state.get("vlm_result") is None
    assert state.get("source_url") is None
    assert state.get("source_key") is None
    assert state.get("image_bytes") is None
    assert state.get("generated_url") is None
    assert state.get("entity") is None
    assert state.get("error") is None


def test_state_partial_update_via_dict_merge() -> None:
    state: CharacterGraphState = {"input": _input()}
    updated: CharacterGraphState = {**state, "source_url": "https://x/y"}
    assert state.get("source_url") is None
    assert updated["source_url"] == "https://x/y"
