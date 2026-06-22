import pytest
from agents.feed_generation.nodes.gen_feed_prompt import gen_feed_prompt_node
from agents.feed_generation.exceptions import PromptGenerationError
from tests.agents.feed_generation.fakes import make_state, make_ports, FakeLLM, FailingLLM

pytestmark = pytest.mark.asyncio


async def test_splits_action_and_scene_and_prepends_visual():
    llm = FakeLLM("action: cleaning a messy room\nscene: cozy sunny bedroom")
    state = make_state()
    cmd = await gen_feed_prompt_node(state, {"configurable": {"ports": make_ports(llm=llm)}})
    fp = cmd.update["feed_prompt"]
    assert "cleaning a messy room" in fp.character
    assert "분홍색 머리" in fp.character          # visual 결합
    assert fp.scene == "cozy sunny bedroom"
    assert cmd.goto == "feed_image"


async def test_missing_scene_falls_back_to_action():
    llm = FakeLLM("action: planting a tree")
    cmd = await gen_feed_prompt_node(make_state(), {"configurable": {"ports": make_ports(llm=llm)}})
    assert "planting a tree" in cmd.update["feed_prompt"].scene


async def test_llm_failure_raises_prompt_error():
    with pytest.raises(PromptGenerationError):
        await gen_feed_prompt_node(make_state(), {"configurable": {"ports": make_ports(llm=FailingLLM())}})


async def test_garbled_llm_output_raises_prompt_error():
    # action:/scene: 마커가 없는 출력 → 파싱 결과 빈 action → PromptGenerationError
    llm = FakeLLM("sorry I cannot help with that")
    with pytest.raises(PromptGenerationError):
        await gen_feed_prompt_node(make_state(), {"configurable": {"ports": make_ports(llm=llm)}})
