from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError


# 검증 대상 기능: Qwen OpenAI 호환 응답 껍데기에서 원문 content 를 꺼낸다.
class _FakeResponse:
    def __init__(self, payload: dict | None = None, *, text: str = "", status_error: Exception | None = None) -> None:
        self._payload = payload
        self.text = text or json.dumps(payload or {})
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("invalid json")
        return self._payload


class _FakeAsyncClient:
    responses: list[_FakeResponse | Exception] = []
    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, endpoint: str, *, headers: dict, json: dict) -> _FakeResponse:
        self.calls.append({"endpoint": endpoint, "headers": headers, "json": json})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def fake_httpx(monkeypatch):
    """기능별 공통 준비: 모든 Qwen HTTP 호출을 메모리 fake 로 대체한다."""
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []
    monkeypatch.setattr("adapters.todo_creation.qwen_llm.httpx.AsyncClient", _FakeAsyncClient)


def _payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


# 입력 검증/파싱: 유효한 원문 JSON 은 TaskCandidate 목록으로 변환된다.
async def test_split_tasks_parses_valid_json() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "title": "코테",
                                "due_date": "2026-05-24",
                                "tags": ["학습"],
                            },
                            {
                                "title": "발표 준비",
                                "due_date": "2026-05-27",
                                "tags": ["업무"],
                            },
                        ]
                    }
                )
            )
        )
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(
        prompt="오늘 코테, 3일 뒤 발표", today=date(2026, 5, 24)
    )
    assert len(out) == 2
    assert out[0].title == "코테"
    assert out[0].tags == ["학습"]


# 프롬프트 계약: today 와 사용자 입력은 user message 에 포함된다.
async def test_split_tasks_sends_today_and_prompt() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(json.dumps({"tasks": []})))
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1", model="Qwen/Qwen2.5-7B-Instruct")
    await llm.split_tasks(prompt="오늘 코테", today=date(2026, 5, 24))

    call = _FakeAsyncClient.calls[0]
    serialized = json.dumps(call["json"]["messages"], ensure_ascii=False)
    assert call["endpoint"] == "http://qwen.test/v1/chat/completions"
    assert call["json"]["model"] == "Qwen/Qwen2.5-7B-Instruct"
    assert "2026-05-24" in serialized
    assert "오늘 코테" in serialized
    assert "tags" in serialized
    assert "todos.content" in serialized
    assert "schedules.title" in serialized


# 원문 파싱 보정: Qwen 이 코드펜스를 섞어도 JSON 본문만 추출한다.
async def test_split_tasks_strips_code_fence() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(
            _payload(
                '```json\n{"tasks":[{"title":"운동가기","due_date":"2026-05-24","tags":["건강"]}]}\n```'
            )
        )
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="오늘 운동 다녀올거야", today=date(2026, 5, 24))
    assert out[0].title == "운동가기"


# 재시도: 첫 응답이 JSON 이 아니면 스키마 강화 메시지로 1회 재요청한다.
async def test_split_tasks_retries_once_on_invalid_json() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload("설명: 할 일을 정리했습니다")),
        _FakeResponse(
            _payload(
                '{"tasks":[{"title":"발표 준비","due_date":"2026-05-27","tags":["학습"]}]}'
            )
        ),
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="3일 뒤 발표 준비", today=date(2026, 5, 24))
    assert out[0].title == "발표 준비"
    assert len(_FakeAsyncClient.calls) == 2
    retry_messages = _FakeAsyncClient.calls[1]["json"]["messages"]
    assert retry_messages[-1]["role"] == "user"
    assert "스키마" in retry_messages[-1]["content"]
    assert "tags" in retry_messages[-1]["content"]


# 실패 처리: HTTP 오류는 LLMFailedError 로 변환된다.
async def test_split_tasks_wraps_http_error() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [httpx.ConnectError("connection failed")]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    with pytest.raises(LLMFailedError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))


# 실패 처리: 두 번 모두 스키마가 틀리면 LLMOutputError 를 반환한다.
async def test_split_tasks_raises_output_error_after_retry() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload('{"unrelated": []}')),
        _FakeResponse(_payload("not json")),
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    with pytest.raises(LLMOutputError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))
