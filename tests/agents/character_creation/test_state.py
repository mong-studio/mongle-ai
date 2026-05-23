from __future__ import annotations

from agents.character_creation.schemas import CharacterCreationInput
from agents.character_creation.state import CharacterGraphState


def _input() -> CharacterCreationInput:
    return CharacterCreationInput(user_id="u1", name="몽글이", persona="다정한 곰")


def test_state_initial_fields_default_to_none() -> None:
    state = CharacterGraphState(input=_input(), is_regeneration=False)
    assert state.route is None
    assert state.llm_result is None
    assert state.vlm_result is None
    assert state.source_url is None
    assert state.source_key is None
    assert state.image_bytes is None
    assert state.generated_url is None
    assert state.entity is None
    assert state.error is None


def test_state_partial_update_via_model_copy() -> None:
    state = CharacterGraphState(input=_input(), is_regeneration=False)
    updated = state.model_copy(update={"route": "text_only"})
    assert state.route is None
    assert updated.route == "text_only"
