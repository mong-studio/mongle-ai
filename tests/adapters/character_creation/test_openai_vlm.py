from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adapters.character_creation.openai_vlm import OpenAIVLM
from agents.character_creation.exceptions import VLMFailedError
from agents.character_creation.schemas import SourceImage


def _completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _image(content_type: str = "image/png", size: int = 1024) -> SourceImage:
    return SourceImage(filename="x.png", content_type=content_type, data=b"\x00" * size)


@pytest.mark.asyncio
async def test_extract_returns_appearance_description() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _completion(
        json.dumps({"appearance_description": "갈색 털의 작은 강아지. 빨간 목줄을 했다."})
    )
    vlm = OpenAIVLM(client=client, model="gpt-4o")
    result = await vlm.extract_appearance(_image())
    assert result.appearance_description.startswith("갈색")


@pytest.mark.asyncio
async def test_extract_sends_base64_image_url() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _completion(
        json.dumps({"appearance_description": "x" * 10})
    )
    vlm = OpenAIVLM(client=client, model="gpt-4o")
    await vlm.extract_appearance(_image(content_type="image/jpeg"))

    msgs = client.chat.completions.create.call_args.kwargs["messages"]
    user_content = msgs[1]["content"]
    assert isinstance(user_content, list)
    image_block = next(b for b in user_content if b.get("type") == "image_url")
    assert image_block["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_extract_raises_on_invalid_json() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _completion("garbage")
    vlm = OpenAIVLM(client=client, model="gpt-4o")
    with pytest.raises(VLMFailedError):
        await vlm.extract_appearance(_image())


@pytest.mark.asyncio
async def test_extract_wraps_client_exception() -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")
    vlm = OpenAIVLM(client=client, model="gpt-4o")
    with pytest.raises(VLMFailedError):
        await vlm.extract_appearance(_image())
