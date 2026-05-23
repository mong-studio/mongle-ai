from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adapters.character_creation.openai_llm import OpenAILLM
from agents.character_creation.exceptions import LLMFailedError
from agents.character_creation.schemas import PersonalityKeyword


def _completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _make_client(content: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = MagicMock(return_value=_completion(content))
    return client


@pytest.mark.asyncio
async def test_generate_persona_returns_parsed_result() -> None:
    payload = json.dumps(
        {
            "personality": "씩씩하고 호기심 많아 매일 새로운 모험을 찾는다. 친구를 잘 챙긴다.",
            "speech_style": "어미를 늘여 말한다. 자주 '아하—' 하고 감탄한다.",
            "background": "마을 뒷산 작은 굴에서 자랐다. 매일 아침 산책을 한다.",
        }
    )
    client = _make_client(payload)
    llm = OpenAILLM(client=client, model="gpt-4o")

    result = await llm.generate_persona(
        persona="용감한 강아지",
        keywords=[PersonalityKeyword.ADVENTUROUS, PersonalityKeyword.CURIOUS],
    )

    assert result.personality.startswith("씩씩")
    assert result.speech_style.startswith("어미를")
    assert result.background.startswith("마을 뒷산")


@pytest.mark.asyncio
async def test_generate_persona_passes_structured_output_schema() -> None:
    payload = json.dumps(
        {"personality": "a", "speech_style": "b", "background": "c"}
    )
    client = _make_client(payload)
    llm = OpenAILLM(client=client, model="gpt-4o")

    await llm.generate_persona(persona="p", keywords=[])

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    rf = kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "LLMPersonaResult"
    assert rf["json_schema"]["strict"] is True
    msgs = kwargs["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "DATA:" in msgs[1]["content"]
    assert "p" in msgs[1]["content"]


@pytest.mark.asyncio
async def test_generate_persona_raises_on_invalid_json() -> None:
    client = _make_client("not json at all")
    llm = OpenAILLM(client=client, model="gpt-4o")
    with pytest.raises(LLMFailedError):
        await llm.generate_persona(persona="p", keywords=[])


@pytest.mark.asyncio
async def test_generate_persona_raises_on_schema_mismatch() -> None:
    client = _make_client(json.dumps({"personality": "only one field"}))
    llm = OpenAILLM(client=client, model="gpt-4o")
    with pytest.raises(LLMFailedError):
        await llm.generate_persona(persona="p", keywords=[])


@pytest.mark.asyncio
async def test_generate_persona_wraps_openai_exception() -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("network down")
    llm = OpenAILLM(client=client, model="gpt-4o")
    with pytest.raises(LLMFailedError):
        await llm.generate_persona(persona="p", keywords=[])
