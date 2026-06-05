from __future__ import annotations

from typing import Any

import httpx
import pytest

from adapters.feed_generation.qwen_llm import QwenLLM
from agents.feed_generation.exceptions import CaptionGenerationError


class _FakeResponse:
    def __init__(self, content: str | None) -> None:
        self.text = str(content)
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self._content}}]}


class _FakeAsyncClient:
    contents: list[str | None | Exception] = []
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
    """기능별 공통 준비: feed caption Qwen HTTP 호출을 fake 로 대체한다."""
    _FakeAsyncClient.contents = []
    _FakeAsyncClient.calls = []
    monkeypatch.setattr("adapters.feed_generation.qwen_llm.httpx.AsyncClient", _FakeAsyncClient)


# 캡션 생성: Qwen 응답 content 를 trim 해서 반환한다.
async def test_qwen_llm_returns_stripped_text():
    _FakeAsyncClient.contents = ["  오늘 청소 완료 ✨  "]
    adapter = QwenLLM(model="Qwen/Qwen2.5-7B-Instruct", base_url="http://localhost:8000/v1")
    result = await adapter.generate("테스트 프롬프트")
    assert result == "오늘 청소 완료 ✨"


# 실패 처리: API 연결 실패는 CaptionGenerationError 로 감싼다.
async def test_qwen_llm_raises_caption_generation_error_on_api_failure():
    _FakeAsyncClient.contents = [httpx.ConnectError("연결 실패")]
    adapter = QwenLLM(model="Qwen/Qwen2.5-7B-Instruct", base_url="http://localhost:8000/v1")
    with pytest.raises(CaptionGenerationError):
        await adapter.generate("프롬프트")


# 프롬프트 계약: 호출자가 만든 caption prompt 를 user message 로 그대로 전달한다.
async def test_qwen_llm_passes_prompt_as_user_message():
    _FakeAsyncClient.contents = ["한국어 캡션"]
    adapter = QwenLLM(model="Qwen/Qwen2.5-7B-Instruct", base_url="http://localhost:8000/v1")
    await adapter.generate("내 프롬프트")

    call_payload = _FakeAsyncClient.calls[0]["json"]
    assert call_payload["messages"][0]["role"] == "user"
    assert call_payload["messages"][0]["content"] == "내 프롬프트"


# 스키마 방어: 빈 content 는 명시적인 CaptionGenerationError 로 처리한다.
async def test_qwen_llm_raises_when_content_is_empty():
    _FakeAsyncClient.contents = [None]
    adapter = QwenLLM(model="Qwen/Qwen2.5-7B-Instruct", base_url="http://localhost:8000/v1")
    with pytest.raises(CaptionGenerationError):
        await adapter.generate("프롬프트")
