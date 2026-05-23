from __future__ import annotations

import pytest

from agents.character_creation.exceptions import ValidationFailedError
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from agents.character_creation.validation import check
from tests.agents.character_creation.fakes import FakeRepository


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


async def test_passes_when_within_all_limits() -> None:
    repo = FakeRepository(active_count=0, regen_count_today=0)
    await check(_input(), repo=repo, is_regeneration=False)


async def test_rejects_when_active_characters_at_limit() -> None:
    repo = FakeRepository(active_count=10)
    with pytest.raises(ValidationFailedError) as exc:
        await check(_input(), repo=repo, is_regeneration=False)
    assert exc.value.code == "C1"


async def test_rejects_when_regen_count_exceeded() -> None:
    repo = FakeRepository(active_count=1, regen_count_today=3)
    with pytest.raises(ValidationFailedError) as exc:
        await check(_input(), repo=repo, is_regeneration=True)
    assert exc.value.code == "C2"


async def test_does_not_check_regen_when_not_regeneration() -> None:
    repo = FakeRepository(active_count=1, regen_count_today=99)
    await check(_input(), repo=repo, is_regeneration=False)


@pytest.mark.parametrize("content_type", ["image/gif", "application/pdf", "text/plain"])
async def test_rejects_disallowed_mime(content_type: str) -> None:
    repo = FakeRepository()
    src = SourceImage(filename="x", content_type=content_type, data=b"\x00")
    with pytest.raises(ValidationFailedError) as exc:
        await check(_input(source_image=src), repo=repo, is_regeneration=False)
    assert exc.value.code == "C3"


async def test_rejects_image_larger_than_5mb() -> None:
    repo = FakeRepository()
    src = SourceImage(
        filename="x.png",
        content_type="image/png",
        data=b"\x00" * (5 * 1024 * 1024 + 1),
    )
    with pytest.raises(ValidationFailedError) as exc:
        await check(_input(source_image=src), repo=repo, is_regeneration=False)
    assert exc.value.code == "C4"


async def test_accepts_image_at_5mb_boundary() -> None:
    repo = FakeRepository()
    src = SourceImage(
        filename="x.png",
        content_type="image/png",
        data=b"\x00" * (5 * 1024 * 1024),
    )
    await check(_input(source_image=src), repo=repo, is_regeneration=False)
