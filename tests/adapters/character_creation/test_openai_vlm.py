from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from adapters.character_creation.openai_vlm import OpenAIVLM
from agents.character_creation.exceptions import VLMFailedError
from agents.character_creation.schemas import SourceImage, VLMResult


def _make_runnable(result: object | None = None, *, side_effect: object = None) -> MagicMock:
    runnable = MagicMock()
    if side_effect is not None:
        runnable.ainvoke = AsyncMock(side_effect=side_effect)
    else:
        runnable.ainvoke = AsyncMock(return_value=result)
    return runnable


def _image(content_type: str = "image/png", size: int = 1024) -> SourceImage:
    return SourceImage(filename="x.png", content_type=content_type, data=b"\x00" * size)


@pytest.mark.asyncio
async def test_extract_returns_appearance_description() -> None:
    expected = VLMResult(appearance_description="갈색 털의 작은 강아지. 빨간 목줄을 했다.")
    runnable = _make_runnable(expected)
    vlm = OpenAIVLM(runnable=runnable)

    result = await vlm.extract_appearance(_image())

    assert result == expected


@pytest.mark.asyncio
async def test_extract_sends_base64_image_url() -> None:
    expected = VLMResult(appearance_description="x" * 10)
    runnable = _make_runnable(expected)
    vlm = OpenAIVLM(runnable=runnable)

    await vlm.extract_appearance(_image(content_type="image/jpeg"))

    messages = runnable.ainvoke.call_args.args[0]
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    user_content = messages[1].content
    assert isinstance(user_content, list)
    image_block = next(b for b in user_content if b.get("type") == "image_url")
    assert image_block["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_extract_raises_on_wrong_type() -> None:
    runnable = _make_runnable({"appearance_description": "x"})
    vlm = OpenAIVLM(runnable=runnable)
    with pytest.raises(VLMFailedError):
        await vlm.extract_appearance(_image())


@pytest.mark.asyncio
async def test_extract_wraps_runnable_exception() -> None:
    runnable = _make_runnable(side_effect=RuntimeError("boom"))
    vlm = OpenAIVLM(runnable=runnable)
    with pytest.raises(VLMFailedError):
        await vlm.extract_appearance(_image())
