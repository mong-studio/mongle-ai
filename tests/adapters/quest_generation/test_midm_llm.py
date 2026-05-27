from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from adapters._shared.openai_compat import reset_cache
from adapters.quest_generation.midm_llm import MidmLLM
from agents.quest_generation.exceptions import LLMFailedError
from agents.quest_generation.schemas import Character


@pytest.fixture(autouse=True)
def _reset_client_cache():
    reset_cache()
    yield
    reset_cache()


def _char() -> Character:
    return Character(
        character_id=uuid4(),
        name="몽돌이",
        personality="호기심 많은",
        speech_style="해요체",
        appearance_keywords=["둥근 얼굴"],
    )


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = type("Msg", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeClient:
    def __init__(self, *, contents: list[str]) -> None:
        self._contents = list(contents)
        self.chat = type("Chat", (), {})()
        self.chat.completions = type("Comp", (), {})()
        self.chat.completions.create = self._create  # type: ignore[attr-defined]
        self.calls: list[dict[str, Any]] = []

    async def _create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if not self._contents:
            raise AssertionError("no more contents")
        return _FakeResponse(self._contents.pop(0))


async def test_midm_parses_valid_json_on_first_attempt(monkeypatch):
    fake = _FakeClient(contents=['{"quest_text": "좋은 아침이에요"}'])
    monkeypatch.setattr(
        "adapters.quest_generation.midm_llm.build_async_client",
        lambda **_: fake,
    )
    llm = MidmLLM(model="midm-mini-instruct", base_url="http://x")
    text = await llm.generate_quest(character=_char())
    assert text == "좋은 아침이에요"
    assert len(fake.calls) == 1
    sent = fake.calls[0]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[1]["role"] == "user"
    assert "몽돌이" in sent[1]["content"]


async def test_midm_strips_code_fences(monkeypatch):
    fake = _FakeClient(contents=['```json\n{"quest_text": "햇볕이 좋아요"}\n```'])
    monkeypatch.setattr(
        "adapters.quest_generation.midm_llm.build_async_client",
        lambda **_: fake,
    )
    llm = MidmLLM(model="m", base_url="http://x")
    assert await llm.generate_quest(character=_char()) == "햇볕이 좋아요"


async def test_midm_retries_once_on_invalid_json(monkeypatch):
    fake = _FakeClient(
        contents=["not json at all", '{"quest_text": "재시도 성공!"}']
    )
    monkeypatch.setattr(
        "adapters.quest_generation.midm_llm.build_async_client",
        lambda **_: fake,
    )
    llm = MidmLLM(model="m", base_url="http://x")
    assert await llm.generate_quest(character=_char()) == "재시도 성공!"
    assert len(fake.calls) == 2


async def test_midm_raises_llm_failed_after_both_attempts(monkeypatch):
    fake = _FakeClient(contents=["junk 1", "junk 2"])
    monkeypatch.setattr(
        "adapters.quest_generation.midm_llm.build_async_client",
        lambda **_: fake,
    )
    llm = MidmLLM(model="m", base_url="http://x")
    with pytest.raises(LLMFailedError):
        await llm.generate_quest(character=_char())
    assert len(fake.calls) == 2


async def test_midm_raises_llm_failed_when_text_too_long(monkeypatch):
    long = "가" * 81
    fake = _FakeClient(
        contents=[
            f'{{"quest_text": "{long}"}}',
            f'{{"quest_text": "{long}"}}',
        ]
    )
    monkeypatch.setattr(
        "adapters.quest_generation.midm_llm.build_async_client",
        lambda **_: fake,
    )
    llm = MidmLLM(model="m", base_url="http://x")
    with pytest.raises(LLMFailedError):
        await llm.generate_quest(character=_char())


async def test_midm_propagates_network_error_as_llm_failed(monkeypatch):
    class _BadClient:
        pass

    bad = _BadClient()
    bad.chat = type("Chat", (), {})()  # type: ignore[attr-defined]
    bad.chat.completions = type("Comp", (), {})()  # type: ignore[attr-defined]

    async def _create(**_: Any) -> _FakeResponse:
        raise ConnectionError("network down")

    bad.chat.completions.create = _create  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "adapters.quest_generation.midm_llm.build_async_client",
        lambda **_: bad,
    )
    llm = MidmLLM(model="m", base_url="http://x")
    with pytest.raises(LLMFailedError):
        await llm.generate_quest(character=_char())
