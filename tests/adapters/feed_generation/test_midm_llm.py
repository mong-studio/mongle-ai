from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.feed_generation.midm_llm import MidmLLM
from agents.feed_generation.exceptions import CaptionGenerationError


async def test_midm_llm_returns_stripped_text():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "  오늘 청소 완료 ✨  "

    with patch("adapters.feed_generation.midm_llm.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai.return_value = mock_client

        adapter = MidmLLM(model="midm-mini", base_url="http://localhost:8000/v1")
        result = await adapter.generate("테스트 프롬프트")

    assert result == "오늘 청소 완료 ✨"


async def test_midm_llm_raises_caption_generation_error_on_api_failure():
    with patch("adapters.feed_generation.midm_llm.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("연결 실패"))
        mock_openai.return_value = mock_client

        adapter = MidmLLM(model="midm-mini", base_url="http://localhost:8000/v1")
        with pytest.raises(CaptionGenerationError):
            await adapter.generate("프롬프트")


async def test_midm_llm_passes_prompt_as_user_message():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "한국어 캡션"

    with patch("adapters.feed_generation.midm_llm.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai.return_value = mock_client

        adapter = MidmLLM(model="midm-mini", base_url="http://localhost:8000/v1")
        await adapter.generate("내 프롬프트")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"][0]["role"] == "user"
        assert call_kwargs["messages"][0]["content"] == "내 프롬프트"
