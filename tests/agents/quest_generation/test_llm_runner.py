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
        # 한국어 전용 검증 가드가 생겨, FakeLLM 출력("{name}의 혼잣말입니다")이 한국어가 되도록 한글 이름 사용.
        name="별이",
        personality="활발한",
        speech_style="반말",
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


async def test_non_korean_output_is_rejected_and_retried():
    # 한자/외국어가 섞인 출력은 검증 실패로 보고 재시도하다가 소진되면 LLMFailedError.
    llm = FakeLLM(text_for=lambda c: "Hello world 任务")
    runner = LLMRunner(llm, max_retries=2)
    with pytest.raises(LLMFailedError):
        await runner.generate(character=_char())
    assert len(llm.calls) == 3


async def test_recovers_when_korean_appears():
    # 1차 비한국어 → 2차 한국어면 한국어 결과를 반환한다.
    seq = iter(["タスク 任务", "산책하기"])
    llm = FakeLLM(text_for=lambda c: next(seq))
    runner = LLMRunner(llm, max_retries=2)
    text = await runner.generate(character=_char())
    assert text == "산책하기"
    assert len(llm.calls) == 2
