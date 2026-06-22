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


async def test_garbled_llm_output_falls_back_to_quest():
    # action:/scene: 마커가 없으면 하드페일하지 않고 원문 quest 로 폴백(피드 생성 보장)
    llm = FakeLLM("죄송하지만 도와드릴 수 없어요")
    cmd = await gen_feed_prompt_node(make_state(), {"configurable": {"ports": make_ports(llm=llm)}})
    fp = cmd.update["feed_prompt"]
    assert "방 청소하기" in fp.character  # quest 폴백
    assert fp.scene == "방 청소하기"
    assert cmd.goto == "feed_image"


async def test_lenient_parse_handles_markdown_and_numbering():
    # 캡션 모델이 마크다운/번호를 붙여도 마커를 탐지
    llm = FakeLLM("1. **action:** baking cookies\n2. **scene:** warm kitchen")
    cmd = await gen_feed_prompt_node(make_state(), {"configurable": {"ports": make_ports(llm=llm)}})
    fp = cmd.update["feed_prompt"]
    assert "baking cookies" in fp.character
    assert fp.scene == "warm kitchen"
