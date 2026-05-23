from __future__ import annotations

from agents.character_creation.router import decide
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from agents.character_creation.state import CharacterGraphState


def _state(*, with_image: bool) -> CharacterGraphState:
    src = (
        SourceImage(filename="a.png", content_type="image/png", data=b"\x89PNG")
        if with_image
        else None
    )
    return CharacterGraphState(
        input=CharacterCreationInput(
            user_id="u1", name="몽글이", persona="다정한 곰", source_image=src
        ),
        is_regeneration=False,
    )


def test_decide_text_only_when_no_image() -> None:
    assert decide(_state(with_image=False)) == ["llm_persona", "vlm_skip"]


def test_decide_image_and_text_when_image_present() -> None:
    assert decide(_state(with_image=True)) == ["llm_persona", "source_upload"]
