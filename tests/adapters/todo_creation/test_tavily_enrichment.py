from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.todo_creation.tavily_enrichment import TavilyEnrichment


def _mock_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_lookup_returns_context_on_success():
    data = {
        "answer": "정처기 2026년 1회 필기: 3월 2일",
        "results": [
            {"content": "정보처리기사 필기 일정: 2026-03-02"},
            {"content": "실기 일정: 2026-05-10"},
        ],
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(data))

    with patch("adapters.todo_creation.tavily_enrichment.httpx.AsyncClient", return_value=mock_client):
        enrichment = TavilyEnrichment(api_key="test-key")
        result = await enrichment.lookup(keyword="정보처리기사", today=date(2026, 6, 10))

    assert result is not None
    assert result["keyword"] == "정보처리기사"
    assert result["year"] == 2026
    assert result["answer"] == "정처기 2026년 1회 필기: 3월 2일"
    assert len(result["snippets"]) == 2


@pytest.mark.asyncio
async def test_lookup_returns_none_when_no_results():
    data = {"answer": None, "results": []}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(data))

    with patch("adapters.todo_creation.tavily_enrichment.httpx.AsyncClient", return_value=mock_client):
        enrichment = TavilyEnrichment(api_key="test-key")
        result = await enrichment.lookup(keyword="정보처리기사", today=date(2026, 6, 10))

    assert result is None


@pytest.mark.asyncio
async def test_lookup_sends_correct_query():
    data = {"answer": "test", "results": [{"content": "info"}]}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(data))

    with patch("adapters.todo_creation.tavily_enrichment.httpx.AsyncClient", return_value=mock_client):
        enrichment = TavilyEnrichment(api_key="my-key")
        await enrichment.lookup(keyword="TOEIC", today=date(2026, 6, 10))

    call_kwargs = mock_client.post.call_args
    payload = call_kwargs.kwargs["json"]
    assert "TOEIC" in payload["query"]
    assert "2026" in payload["query"]
    assert payload["api_key"] == "my-key"


@pytest.mark.asyncio
async def test_lookup_extracts_structured_future_exam_dates():
    data = {
        "answer": "정보처리기사 2026년 3회 필기 2026-07-05, 실기 2026-08-17",
        "results": [
            {"content": "필기시험 2026-07-05 / 원서접수 2026-06-20"},
            {"content": "실기시험 2026-08-17"},
        ],
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(data))

    with patch("adapters.todo_creation.tavily_enrichment.httpx.AsyncClient", return_value=mock_client):
        enrichment = TavilyEnrichment(api_key="k")
        result = await enrichment.lookup(keyword="정보처리기사", today=date(2026, 6, 10))

    assert result is not None
    dates = {d["date"] for d in result["exam_dates"]}
    assert "2026-07-05" in dates
    assert "2026-08-17" in dates
    assert "2026-06-20" not in dates  # 원서접수일 제외
    assert result["suggested_deadline"] == "2026-07-05"  # 가장 가까운 미래 시험일


@pytest.mark.asyncio
async def test_lookup_uses_official_domain_whitelist():
    data = {"answer": "x", "results": [{"content": "info"}]}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(data))

    with patch("adapters.todo_creation.tavily_enrichment.httpx.AsyncClient", return_value=mock_client):
        enrichment = TavilyEnrichment(api_key="k")
        await enrichment.lookup(keyword="정보처리기사", today=date(2026, 6, 10))

    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["include_domains"] == ["q-net.or.kr"]


@pytest.mark.asyncio
async def test_lookup_no_domain_for_unknown_keyword():
    data = {"answer": "x", "results": [{"content": "info"}]}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(data))

    with patch("adapters.todo_creation.tavily_enrichment.httpx.AsyncClient", return_value=mock_client):
        enrichment = TavilyEnrichment(api_key="k")
        await enrichment.lookup(keyword="듣도보도못한시험", today=date(2026, 6, 10))

    payload = mock_client.post.call_args.kwargs["json"]
    assert "include_domains" not in payload
