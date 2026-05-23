from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from adapters.character_creation.openai_llm import OpenAILLM
from agents.character_creation.exceptions import LLMFailedError
from agents.character_creation.schemas import LLMPersonaResult, PersonalityKeyword


def _make_runnable(result: object | None = None, *, side_effect: object = None) -> MagicMock:
    runnable = MagicMock()
    if side_effect is not None:
        runnable.ainvoke = AsyncMock(side_effect=side_effect)
    else:
        runnable.ainvoke = AsyncMock(return_value=result)
    return runnable


@pytest.mark.asyncio
async def test_generate_persona_returns_structured_result() -> None:
    expected = LLMPersonaResult(
        personality="씩씩하고 호기심 많아 매일 새로운 모험을 찾는다. 친구를 잘 챙긴다.",
        speech_style="어미를 늘여 말한다. 자주 '아하—' 하고 감탄한다.",
        background="마을 뒷산 작은 굴에서 자랐다. 매일 아침 산책을 한다.",
    )
    runnable = _make_runnable(expected)
    llm = OpenAILLM(runnable=runnable)

    result = await llm.generate_persona(
        persona="용감한 강아지",
        keywords=[PersonalityKeyword.ADVENTUROUS, PersonalityKeyword.CURIOUS],
    )

    assert result == expected


@pytest.mark.asyncio
async def test_generate_persona_sends_system_and_user_messages() -> None:
    expected = LLMPersonaResult(personality="a", speech_style="b", background="c")
    runnable = _make_runnable(expected)
    llm = OpenAILLM(runnable=runnable)

    await llm.generate_persona(persona="p", keywords=[])

    messages = runnable.ainvoke.call_args.args[0]
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert "DATA:" in messages[1].content
    assert "p" in messages[1].content


@pytest.mark.asyncio
async def test_generate_persona_raises_on_wrong_type() -> None:
    runnable = _make_runnable({"personality": "x", "speech_style": "y", "background": "z"})
    llm = OpenAILLM(runnable=runnable)
    with pytest.raises(LLMFailedError):
        await llm.generate_persona(persona="p", keywords=[])


@pytest.mark.asyncio
async def test_generate_persona_wraps_runnable_exception() -> None:
    runnable = _make_runnable(side_effect=RuntimeError("network down"))
    llm = OpenAILLM(runnable=runnable)
    with pytest.raises(LLMFailedError):
        await llm.generate_persona(persona="p", keywords=[])
