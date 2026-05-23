from __future__ import annotations

import pytest

from agents.character_creation.exceptions import ValidationFailedError
from agents.character_creation.nodes.validate import validate_node
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from agents.character_creation.state import CharacterGraphState
from tests.agents.character_creation.fakes import FakeRepository


def _state(*, with_image: bool, is_regen: bool = False) -> CharacterGraphState:
    src = (
        SourceImage(filename="a.png", content_type="image/png", data=b"\x89PNG")
        if with_image
        else None
    )
    return CharacterGraphState(
        input=CharacterCreationInput(
            user_id="u1", name="몽글이", persona="다정한 곰", source_image=src
        ),
        is_regeneration=is_regen,
    )


def _config(repo: FakeRepository) -> dict:
    class _Ports:
        repository = repo
    return {"configurable": {"ports": _Ports()}}


async def test_validate_node_text_only_sets_route() -> None:
    out = await validate_node(_state(with_image=False), _config(FakeRepository()))
    assert out == {"route": "text_only"}


async def test_validate_node_image_present_sets_route() -> None:
    out = await validate_node(_state(with_image=True), _config(FakeRepository()))
    assert out == {"route": "image_and_text"}


async def test_validate_node_propagates_validation_error() -> None:
    with pytest.raises(ValidationFailedError):
        await validate_node(
            _state(with_image=False),
            _config(FakeRepository(active_count=10)),
        )
