from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from adapters.todo_creation.runpod_llm import RunPodQwenLLM
from agents.todo_creation.exceptions import LLMFailedError

ENDPOINT = "https://api.runpod.ai/v2/test-ep"
MESSAGES = [{"role": "user", "content": "안녕"}]
_PATCH = "adapters.todo_creation.runpod_llm.httpx.AsyncClient"


def _llm(**kw) -> RunPodQwenLLM:
    defaults = dict(endpoint_url=ENDPOINT, api_key="rp-key", adapter="planner", poll_interval=0.0, poll_timeout=5.0)
    defaults.update(kw)
    return RunPodQwenLLM(**defaults)


def _mock_client(*, statuses: list[dict], run_id: str = "job-1") -> AsyncMock:
    run_r = MagicMock()
    run_r.raise_for_status = MagicMock()
    run_r.json.return_value = {"id": run_id}

    status_rs = []
    for s in statuses:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = s
        status_rs.append(r)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=run_r)
    client.get = AsyncMock(side_effect=status_rs)
    return client


@pytest.mark.asyncio
async def test_completed_returns_text() -> None:
    client = _mock_client(statuses=[{"status": "COMPLETED", "output": {"text": "결과"}}])
    with patch(_PATCH, return_value=client):
        result = await _llm().complete_raw(messages=MESSAGES)
    assert result == "결과"


@pytest.mark.asyncio
async def test_polls_until_completed() -> None:
    client = _mock_client(statuses=[
        {"status": "IN_QUEUE"},
        {"status": "IN_PROGRESS"},
        {"status": "COMPLETED", "output": {"text": "완료"}},
    ])
    with patch(_PATCH, return_value=client):
        result = await _llm().complete_raw(messages=MESSAGES)
    assert result == "완료"
    assert client.get.call_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["FAILED", "CANCELLED", "TIMED_OUT"])
async def test_terminal_status_raises(status: str) -> None:
    client = _mock_client(statuses=[{"status": status, "error": "OOM"}])
    with patch(_PATCH, return_value=client):
        with pytest.raises(LLMFailedError):
            await _llm().complete_raw(messages=MESSAGES)


@pytest.mark.asyncio
async def test_submit_http_error_raises() -> None:
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(side_effect=httpx.HTTPError("conn error"))
    with patch(_PATCH, return_value=client):
        with pytest.raises(LLMFailedError, match="submit"):
            await _llm().complete_raw(messages=MESSAGES)


@pytest.mark.asyncio
async def test_poll_errors_exhausted_raises() -> None:
    run_r = MagicMock()
    run_r.raise_for_status = MagicMock()
    run_r.json.return_value = {"id": "job-1"}

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=run_r)
    client.get = AsyncMock(side_effect=httpx.HTTPError("poll error"))
    with patch(_PATCH, return_value=client):
        with pytest.raises(LLMFailedError, match="repeatedly"):
            await _llm().complete_raw(messages=MESSAGES)


@pytest.mark.asyncio
async def test_missing_output_text_raises() -> None:
    client = _mock_client(statuses=[{"status": "COMPLETED", "output": {}}])
    with patch(_PATCH, return_value=client):
        with pytest.raises(LLMFailedError, match="output.text"):
            await _llm().complete_raw(messages=MESSAGES)


@pytest.mark.asyncio
async def test_timeout_raises() -> None:
    client = _mock_client(statuses=[{"status": "IN_PROGRESS"}] * 10)
    with patch(_PATCH, return_value=client):
        with pytest.raises(LLMFailedError, match="timed out"):
            await _llm(poll_timeout=0.0).complete_raw(messages=MESSAGES)


@pytest.mark.asyncio
async def test_payload_includes_adapter() -> None:
    """멀티-LoRA 엔드포인트가 어댑터를 고를 수 있도록 input.adapter 를 보낸다."""
    client = _mock_client(statuses=[{"status": "COMPLETED", "output": {"text": "ok"}}])
    with patch(_PATCH, return_value=client):
        await _llm(adapter="planner").complete_raw(messages=MESSAGES)
    sent = client.post.call_args.kwargs["json"]
    assert sent["input"]["adapter"] == "planner"
