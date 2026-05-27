import pytest
from agents.feed_generation.exceptions import CaptionGenerationError
from agents.feed_generation.nodes.llm_caption import llm_caption_node
from tests.agents.feed_generation.fakes import (
    FakeLLM,
    FailingLLM,
    make_ports,
    make_state,
)


async def test_llm_caption_node_sets_raw_caption_and_routes_to_validate_caption():
    fake_llm = FakeLLM(caption="청소 완료! ✨")
    ports = make_ports(llm=fake_llm)
    state = make_state(caption_ctx="당신은 몽글이입니다...")
    config = {"configurable": {"ports": ports}}

    cmd = await llm_caption_node(state, config)

    assert cmd.goto == "validate_caption"
    assert cmd.update["raw_caption"] == "청소 완료! ✨"


async def test_llm_caption_node_passes_full_prompt_to_llm():
    fake_llm = FakeLLM()
    ports = make_ports(llm=fake_llm)
    state = make_state(caption_ctx="테스트 프롬프트")
    config = {"configurable": {"ports": ports}}

    await llm_caption_node(state, config)

    assert fake_llm.calls[0] == "테스트 프롬프트"


async def test_llm_caption_node_wraps_port_error_as_caption_generation_error():
    ports = make_ports(llm=FailingLLM())
    state = make_state(caption_ctx="프롬프트")
    config = {"configurable": {"ports": ports}}

    with pytest.raises(CaptionGenerationError):
        await llm_caption_node(state, config)
