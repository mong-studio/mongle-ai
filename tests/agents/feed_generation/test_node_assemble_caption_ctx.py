from agents.feed_generation.nodes.assemble_caption_ctx import (
    assemble_caption_ctx_node,
    _build_caption_prompt,
)
from tests.agents.feed_generation.fakes import make_state, make_input


async def test_assemble_caption_ctx_sets_prompt_and_routes_to_llm_caption():
    state = make_state(image_prompt="분홍 머리, anime style")
    cmd = await assemble_caption_ctx_node(state, {})

    assert cmd.goto == "llm_caption"
    assert cmd.update["caption_ctx"]
    assert isinstance(cmd.update["caption_ctx"], str)


async def test_caption_prompt_includes_character_speech_style():
    inp = make_input()
    prompt = _build_caption_prompt(inp.character, inp.quest, "분홍 머리, anime")
    assert inp.character.speech_style in prompt


async def test_caption_prompt_includes_quest_text():
    inp = make_input()
    prompt = _build_caption_prompt(inp.character, inp.quest, "분홍 머리, anime")
    assert inp.quest.quest_text in prompt


async def test_caption_prompt_includes_image_prompt():
    inp = make_input()
    image_prompt = "분홍 머리, 큰 눈, anime"
    prompt = _build_caption_prompt(inp.character, inp.quest, image_prompt)
    assert image_prompt in prompt
