import pytest

from agents.feed_generation.nodes.gen_feed_prompt import gen_feed_prompt_node
from tests.agents.feed_generation.fakes import make_input, make_state

pytestmark = pytest.mark.asyncio


async def test_character_combines_visual_and_quest():
    state = make_state()  # visual=["분홍색 머리", ...], quest="방 청소하기"
    cmd = await gen_feed_prompt_node(state, {})
    fp = cmd.update["feed_prompt"]
    assert "방 청소하기" in fp.character   # quest = action
    assert "분홍색 머리" in fp.character   # visual 결합
    assert fp.scene == "방 청소하기"        # quest = scene (pass-through)
    assert cmd.goto == "feed_image"


async def test_no_visual_uses_quest_only():
    inp = make_input()
    inp = inp.model_copy(update={"character": inp.character.model_copy(update={"visual": []})})
    cmd = await gen_feed_prompt_node(make_state(input=inp), {})
    assert cmd.update["feed_prompt"].character == "방 청소하기"


async def test_does_not_call_llm():
    # gen_feed_prompt 는 더 이상 LLM 을 호출하지 않는다(실패 지점 제거).
    from tests.agents.feed_generation.fakes import FakeLLM, make_ports

    llm = FakeLLM()
    await gen_feed_prompt_node(make_state(), {"configurable": {"ports": make_ports(llm=llm)}})
    assert llm.calls == []
