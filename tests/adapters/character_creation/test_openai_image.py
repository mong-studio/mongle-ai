from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adapters.character_creation.openai_image import OpenAIImageGenerator
from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.schemas import LLMPersonaResult, VLMResult


def _image_response(png_bytes: bytes = b"\x89PNG\r\n\x1a\n") -> SimpleNamespace:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return SimpleNamespace(data=[SimpleNamespace(b64_json=b64)])


def _llm_result() -> LLMPersonaResult:
    return LLMPersonaResult(
        personality="씩씩하고 호기심 많은 강아지",
        speech_style="씩씩한 말투",
        background="마을 뒷산 작은 굴에서 자란다",
    )


@pytest.mark.asyncio
async def test_generate_decodes_b64_to_bytes() -> None:
    client = MagicMock()
    client.images.generate.return_value = _image_response(b"\x89PNGDATA")
    gen = OpenAIImageGenerator(client=client, model="gpt-image-1", size="1024x1024")

    out = await gen.generate(
        user_id="u1", llm_result=_llm_result(), vlm_result=None, fallback_persona="용감한 강아지"
    )
    assert out == b"\x89PNGDATA"


@pytest.mark.asyncio
async def test_generate_includes_style_guard_and_vlm_description() -> None:
    client = MagicMock()
    client.images.generate.return_value = _image_response()
    gen = OpenAIImageGenerator(client=client, model="gpt-image-1", size="1024x1024")

    vlm = VLMResult(appearance_description="갈색 털, 빨간 목줄")
    await gen.generate(user_id="u1", llm_result=_llm_result(), vlm_result=vlm, fallback_persona=None)

    kwargs = client.images.generate.call_args.kwargs
    assert kwargs["model"] == "gpt-image-1"
    assert kwargs["size"] == "1024x1024"
    prompt = kwargs["prompt"]
    assert "8-bit pixel art" in prompt
    assert "갈색 털" in prompt
    assert "씩씩하고 호기심" in prompt


@pytest.mark.asyncio
async def test_generate_uses_fallback_persona_when_no_vlm() -> None:
    client = MagicMock()
    client.images.generate.return_value = _image_response()
    gen = OpenAIImageGenerator(client=client, model="gpt-image-1", size="1024x1024")

    await gen.generate(
        user_id="u1", llm_result=_llm_result(), vlm_result=None, fallback_persona="용감한 강아지"
    )
    prompt = client.images.generate.call_args.kwargs["prompt"]
    assert "용감한 강아지" in prompt


@pytest.mark.asyncio
async def test_generate_wraps_client_exception() -> None:
    client = MagicMock()
    client.images.generate.side_effect = RuntimeError("rate limit")
    gen = OpenAIImageGenerator(client=client, model="gpt-image-1", size="1024x1024")
    with pytest.raises(ImageGenerationFailedError):
        await gen.generate(
            user_id="u1", llm_result=_llm_result(), vlm_result=None, fallback_persona="x"
        )


@pytest.mark.asyncio
async def test_generate_raises_when_response_missing_b64() -> None:
    client = MagicMock()
    client.images.generate.return_value = SimpleNamespace(data=[])
    gen = OpenAIImageGenerator(client=client, model="gpt-image-1", size="1024x1024")
    with pytest.raises(ImageGenerationFailedError):
        await gen.generate(
            user_id="u1", llm_result=_llm_result(), vlm_result=None, fallback_persona="x"
        )
