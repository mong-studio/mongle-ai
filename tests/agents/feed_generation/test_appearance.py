import pytest

from agents.feed_generation.appearance import payload_from_visual
from agents.feed_generation.nodes.feed_image import feed_image_node
from agents.feed_generation.schemas import FeedPrompt
from tests.agents.feed_generation.fakes import (
    FakeImageGenerator,
    make_input,
    make_ports,
    make_state,
)

# 실제 서비스의 v2 이전 캐릭터 visual 들(빈 문자열·한국어 포함)
_REAL_VISUALS = [
    "alpaca, bright green and white fur, white face, sparkles when spits saliva",
    "cute rabbit, soft brown fur, big ears, red eyes, smiling nose",
    "toy poodle, short fur, bright yellow, cute face",
    "pixel-art, soldier, green and brown, armor, red scarf, muscular, brave eyes",
    "16x16 픽셀 아트, 파란 모자를 쓴 귀여운 캐릭터",
    "",
]


def test_deterministic():
    """같은 visual → 항상 같은 payload (피드 일관성)."""
    v = ["cute rabbit, soft brown fur, big ears"]
    assert payload_from_visual(v) == payload_from_visual(v)


def test_always_non_empty_with_required_keys():
    """빈 visual 도 non-empty payload 반환(피드 500 방지)."""
    for visual in _REAL_VISUALS:
        p = payload_from_visual([visual] if visual else [])
        assert p["character_summary"], f"empty summary for {visual!r}"
        assert p["character_type"]
        assert "must_preserve" in p and "main_colors" in p


def test_extracts_type_color_accessory():
    p = payload_from_visual(["cute rabbit, soft brown fur, red scarf"])
    assert p["character_type"] == "rabbit"          # 앞 수식어 'cute' 제거
    assert "brown" in p["main_colors"]
    assert any("scarf" in a for a in p["accessories"])


def test_accepts_str_and_list():
    assert payload_from_visual("cat, white") == payload_from_visual(["cat, white"])


pytestmark_async = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_node_synthesizes_when_payload_missing():
    """appearance_payload 없는 캐릭터 → 노드가 visual 로 합성해 워커에 넘긴다."""
    gen = FakeImageGenerator()
    inp = make_input(
        character=make_input().character.model_copy(
            update={"appearance_payload": None, "visual": ["cute rabbit, brown fur"]}
        )
    )
    state = make_state(input=inp, feed_prompt=FeedPrompt(character="rabbit, run", scene="field"))
    await feed_image_node(state, {"configurable": {"ports": make_ports(image_generator=gen)}})
    _ref, _char, _scene, payload = gen.feed_calls[0]
    assert payload is not None
    assert payload["character_summary"] == "cute rabbit, brown fur"


@pytest.mark.asyncio
async def test_node_keeps_real_payload_when_present():
    """payload 있는 신규 캐릭터는 합성하지 않고 그대로 사용."""
    gen = FakeImageGenerator()
    state = make_state(feed_prompt=FeedPrompt(character="x", scene="y"))
    await feed_image_node(state, {"configurable": {"ports": make_ports(image_generator=gen)}})
    _ref, _char, _scene, payload = gen.feed_calls[0]
    assert payload == state["input"].character.appearance_payload
