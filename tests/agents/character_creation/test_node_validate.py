from __future__ import annotations

import pytest

from agents.character_creation.exceptions import ValidationFailedError
from agents.character_creation.nodes.validate import validate_node
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from agents.character_creation.state import CharacterGraphState


def _state(*, with_image: bool, bad_mime: bool = False) -> CharacterGraphState:
    if with_image:
        src = SourceImage(
            filename="a.png",
            content_type="application/pdf" if bad_mime else "image/png",
            data=b"\x89PNG",
        )
    else:
        src = None
    return CharacterGraphState(
        input=CharacterCreationInput(
            user_id="u1", name="몽글이", persona="다정한 곰", source_image=src
        ),
    )


_CONFIG: dict = {"configurable": {}}


async def test_validate_node_text_only_fans_out_to_llm_and_vlm() -> None:
    out = await validate_node(_state(with_image=False), _CONFIG)
    assert out.goto == ["llm_persona", "vlm_analyzer"]
    assert out.update is None


async def test_validate_node_image_present_fans_out_to_llm_and_source_upload() -> None:
    out = await validate_node(_state(with_image=True), _CONFIG)
    assert out.goto == ["llm_persona", "source_upload"]
    assert out.update is None


async def test_validate_node_propagates_validation_error() -> None:
    with pytest.raises(ValidationFailedError):
        await validate_node(_state(with_image=True, bad_mime=True), _CONFIG)
