from __future__ import annotations

import pytest

from agents.character_creation.exceptions import ValidationFailedError
from agents.character_creation.nodes.validate import check
from agents.character_creation.schemas import CharacterCreationInput, SourceImage


def _input(**overrides) -> CharacterCreationInput:
    defaults = {
        "user_id": "u",
        "name": "몽글이",
        "persona": "다정한 곰",
        "personality_keywords": [],
        "source_image": None,
    }
    defaults.update(overrides)
    return CharacterCreationInput(**defaults)


def test_passes_when_no_image() -> None:
    check(_input())


@pytest.mark.parametrize("content_type", ["image/gif", "application/pdf", "text/plain"])
def test_rejects_disallowed_mime(content_type: str) -> None:
    src = SourceImage(filename="x", content_type=content_type, data=b"\x00")
    with pytest.raises(ValidationFailedError) as exc:
        check(_input(source_image=src))
    assert exc.value.code == "C3"


def test_rejects_image_larger_than_5mb() -> None:
    src = SourceImage(
        filename="x.png",
        content_type="image/png",
        data=b"\x00" * (5 * 1024 * 1024 + 1),
    )
    with pytest.raises(ValidationFailedError) as exc:
        check(_input(source_image=src))
    assert exc.value.code == "C4"


def test_accepts_image_at_5mb_boundary() -> None:
    src = SourceImage(
        filename="x.png",
        content_type="image/png",
        data=b"\x00" * (5 * 1024 * 1024),
    )
    check(_input(source_image=src))
