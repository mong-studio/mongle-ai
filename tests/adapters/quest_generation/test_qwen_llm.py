from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

from adapters.quest_generation.qwen_llm import QwenLLM
from agents.quest_generation.exceptions import LLMFailedError
from agents.quest_generation.schemas import Character


def _char() -> Character:
    return Character(
        character_id=uuid4(),
        name="몽돌이",
        personality="호기심 많은",
        speech_style="해요체",
        appearance_keywords=["둥근 얼굴"],
    )


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.text = content
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self._content}}]}


class _FakeAsyncClient:
    contents: list[str | Exception] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, endpoint: str, *, headers: dict, json: dict) -> _FakeResponse:
        self.calls.append({"endpoint": endpoint, "headers": headers, "json": json})
        item = self.contents.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


@pytest.fixture(autouse=True)
def fake_httpx(monkeypatch):
    """기능별 공통 준비: quest Qwen HTTP 호출을 fake 로 대체한다."""
    _FakeAsyncClient.contents = []
    _FakeAsyncClient.calls = []
    monkeypatch.setattr("adapters.quest_generation.qwen_llm.httpx.AsyncClient", _FakeAsyncClient)


# 구조화 출력: 유효한 quest_text JSON 을 첫 시도에서 파싱한다.
async def test_qwen_parses_valid_json_on_first_attempt():
    _FakeAsyncClient.contents = ['{"quest_text": "좋은 아침이에요"}']
    llm = QwenLLM(model="Qwen/Qwen2.5-7B-Instruct", base_url="http://x/v1")
    text = await llm.generate_quest(character=_char())
    assert text == "좋은 아침이에요"
    assert len(_FakeAsyncClient.calls) == 1
    sent = _FakeAsyncClient.calls[0]["json"]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[1]["role"] == "user"
    assert "몽돌이" in sent[1]["content"]


# raw 보정: 코드펜스가 섞인 JSON 도 본문만 추출한다.
async def test_qwen_strips_code_fences():
    _FakeAsyncClient.contents = ['```json\n{"quest_text": "햇볕이 좋아요"}\n```']
    llm = QwenLLM(model="m", base_url="http://x/v1")
    assert await llm.generate_quest(character=_char()) == "햇볕이 좋아요"


# 재시도: 첫 응답이 JSON 이 아니면 schema 강화 메시지로 1회 재요청한다.
async def test_qwen_retries_once_on_invalid_json():
    _FakeAsyncClient.contents = ["not json at all", '{"quest_text": "재시도 성공!"}']
    llm = QwenLLM(model="m", base_url="http://x/v1")
    assert await llm.generate_quest(character=_char()) == "재시도 성공!"
    assert len(_FakeAsyncClient.calls) == 2


# 실패 처리: 두 번 모두 파싱 실패하면 LLMFailedError 를 반환한다.
async def test_qwen_raises_llm_failed_after_both_attempts():
    _FakeAsyncClient.contents = ["junk 1", "junk 2"]
    llm = QwenLLM(model="m", base_url="http://x/v1")
    with pytest.raises(LLMFailedError):
        await llm.generate_quest(character=_char())
    assert len(_FakeAsyncClient.calls) == 2


# 스키마 검증: quest_text 는 80자 이하여야 한다.
async def test_qwen_raises_llm_failed_when_text_too_long():
    long = "가" * 81
    _FakeAsyncClient.contents = [
        f'{{"quest_text": "{long}"}}',
        f'{{"quest_text": "{long}"}}',
    ]
    llm = QwenLLM(model="m", base_url="http://x/v1")
    with pytest.raises(LLMFailedError):
        await llm.generate_quest(character=_char())


# 외부 장애: HTTP 연결 실패는 LLMFailedError 로 변환한다.
async def test_qwen_propagates_network_error_as_llm_failed():
    _FakeAsyncClient.contents = [httpx.ConnectError("network down")]
    llm = QwenLLM(model="m", base_url="http://x/v1")
    with pytest.raises(LLMFailedError):
        await llm.generate_quest(character=_char())
