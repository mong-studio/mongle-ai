from __future__ import annotations

from uuid import uuid4

import pytest

from agents.quest_generation._llm_runner import LLMRunner
from agents.quest_generation.exceptions import LLMFailedError
from agents.quest_generation.schemas import Character
from tests.agents.quest_generation.fakes import FakeLLM


def _char() -> Character:
    return Character(
        character_id=uuid4(),
        name="X",
        personality="p",
        speech_style="s",
        appearance_keywords=[],
    )


async def test_first_attempt_success():
    llm = FakeLLM()
    runner = LLMRunner(llm, max_retries=2)
    text = await runner.generate(character=_char())
    assert text.endswith("혼잣말입니다.")
    assert len(llm.calls) == 1


async def test_succeeds_on_third_attempt():
    llm = FakeLLM(fail_times=2)
    runner = LLMRunner(llm, max_retries=2)
    text = await runner.generate(character=_char())
    assert text.endswith("혼잣말입니다.")
    assert len(llm.calls) == 3


async def test_all_attempts_fail_raises_llm_failed():
    llm = FakeLLM(fail_times=99)
    runner = LLMRunner(llm, max_retries=2)
    with pytest.raises(LLMFailedError):
        await runner.generate(character=_char())
    assert len(llm.calls) == 3   # 1 + 2 retries


async def test_zero_retries_means_single_attempt():
    llm = FakeLLM(fail_times=1)
    runner = LLMRunner(llm, max_retries=0)
    with pytest.raises(LLMFailedError):
        await runner.generate(character=_char())
    assert len(llm.calls) == 1
