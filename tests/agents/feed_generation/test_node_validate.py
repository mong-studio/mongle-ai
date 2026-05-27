from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents.feed_generation.exceptions import InputValidationError
from agents.feed_generation.nodes.validate import validate_node
from agents.feed_generation.schemas import CharacterRef, FeedGenerationInput, QuestRef
from tests.agents.feed_generation.fakes import make_state


async def test_validate_valid_input_routes_to_assemble_image_prompt():
    state = make_state()
    cmd = await validate_node(state, {})
    assert cmd.goto == "assemble_image_prompt"


async def test_validate_empty_image_url_raises():
    state = make_state(
        input=FeedGenerationInput(
            quest=QuestRef(quest_id=uuid4(), quest_text="청소"),
            character=CharacterRef(
                character_id=uuid4(),
                name="몽글",
                personality="밝음",
                speech_style="반말",
                appearance_keywords=[],
                image_url="   ",
            ),
        )
    )
    with pytest.raises(InputValidationError) as exc_info:
        await validate_node(state, {})
    assert exc_info.value.code == "empty_image_url"


async def test_validate_empty_quest_text_is_caught_by_pydantic():
    with pytest.raises(ValidationError):
        FeedGenerationInput(
            quest=QuestRef(quest_id=uuid4(), quest_text=""),
            character=CharacterRef(
                character_id=uuid4(),
                name="몽글",
                personality="밝음",
                speech_style="반말",
                appearance_keywords=[],
                image_url="https://s3.example.com/c.png",
            ),
        )
