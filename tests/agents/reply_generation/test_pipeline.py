from __future__ import annotations

from uuid import uuid4

import pytest

from agents.reply_generation import pipeline
from agents.reply_generation.exceptions import ReplyValidationError
from agents.reply_generation.protocols import Ports
from agents.reply_generation.schemas import CharacterRef, ReplyGenerationInput


def _inp() -> ReplyGenerationInput:
    return ReplyGenerationInput(
        character=CharacterRef(
            character_id=uuid4(),
            name="콩이",
            personality="명랑하고 긍정적",
            speech_style="반말, ㅎㅎ를 자주 씀",
        ),
        post_caption="우편함 다 점검했어!",
        user_comment="고생했어! 힘들었지?",
    )


class _FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return self._replies.pop(0)


# 정상: 유효한 답글을 첫 시도에서 반환한다.
async def test_returns_valid_reply():
    llm = _FakeLLM(["응 좀 힘들었지만 보람 있어 ㅎㅎ"])
    out = await pipeline.run(_inp(), ports=Ports(llm=llm))
    assert out.reply_text == "응 좀 힘들었지만 보람 있어 ㅎㅎ"
    assert llm.calls == 1


# 재시도: 50자 초과면 1회 재요청 후 유효 답글을 반환한다.
async def test_retries_once_on_too_long():
    llm = _FakeLLM(["가" * 51, "짧은 답글이야 ㅎㅎ"])
    out = await pipeline.run(_inp(), ports=Ports(llm=llm))
    assert out.reply_text == "짧은 답글이야 ㅎㅎ"
    assert llm.calls == 2


# 실패: 두 번 모두 무효면 ReplyValidationError 를 던진다.
async def test_raises_when_both_invalid():
    llm = _FakeLLM(["가" * 51, "中文 답글"])
    with pytest.raises(ReplyValidationError):
        await pipeline.run(_inp(), ports=Ports(llm=llm))
    assert llm.calls == 2
