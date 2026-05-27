from agents.feed_generation.nodes.assemble_image_prompt import (
    assemble_image_prompt_node,
    _build_image_prompt,
)
from tests.agents.feed_generation.fakes import make_state, make_input


async def test_assemble_image_prompt_sets_prompt_and_routes_to_img2img():
    state = make_state()
    cmd = await assemble_image_prompt_node(state, {})
    assert cmd.goto == "img2img"
    assert cmd.update["image_prompt"]
    assert isinstance(cmd.update["image_prompt"], str)
    assert len(cmd.update["image_prompt"]) > 0


async def test_image_prompt_includes_appearance_keywords():
    inp = make_input()
    prompt = _build_image_prompt(inp.character, inp.quest)
    for kw in inp.character.appearance_keywords:
        assert kw in prompt


async def test_image_prompt_includes_quest_text():
    inp = make_input()
    prompt = _build_image_prompt(inp.character, inp.quest)
    assert inp.quest.quest_text in prompt
