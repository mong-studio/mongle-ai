from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.todo_creation.planner.nodes.enrichment import _detect_keyword, enrichment_node


def test_detect_keyword_jeongchogi():
    assert _detect_keyword("정처기 시험 있어") == "정보처리기사"


def test_detect_keyword_full_name():
    assert _detect_keyword("정보처리기사 필기 준비") == "정보처리기사"


def test_detect_keyword_toeic():
    assert _detect_keyword("토익 800점 목표") == "TOEIC"


def test_detect_keyword_none():
    assert _detect_keyword("운동 계획 짜줘") is None


def test_detect_keyword_case_insensitive():
    assert _detect_keyword("TOEIC 시험 준비") == "TOEIC"


def _config(ports) -> dict:
    return {"configurable": {"ports": ports}}


@pytest.mark.asyncio
async def test_skips_when_already_done():
    state = {"enrichment_done": True, "message": "정처기 시험 있어"}
    result = await enrichment_node(state, _config(MagicMock()))
    assert result == {}


@pytest.mark.asyncio
async def test_returns_done_when_no_keyword():
    state = {"message": "운동 계획 짜줘"}
    result = await enrichment_node(state, _config(MagicMock()))
    assert result == {"enrichment_done": True}


@pytest.mark.asyncio
async def test_returns_done_when_no_enrichment_port():
    ports = MagicMock(spec=[])  # enrichment 속성 없음
    state = {"message": "정처기 시험 있어"}
    result = await enrichment_node(state, _config(ports))
    assert result == {"enrichment_done": True}


@pytest.mark.asyncio
async def test_stores_enrichment_context_on_success():
    mock_context = {"keyword": "정보처리기사", "year": 2026, "snippets": ["필기 6월"]}
    enrichment_port = AsyncMock()
    enrichment_port.lookup = AsyncMock(return_value=mock_context)
    ports = MagicMock()
    ports.enrichment = enrichment_port

    state = {"message": "정처기 시험 있어", "today": date(2026, 6, 10)}
    result = await enrichment_node(state, _config(ports))

    assert result["enrichment_context"] == mock_context
    assert result["enrichment_done"] is True
    enrichment_port.lookup.assert_awaited_once_with(keyword="정보처리기사", today=date(2026, 6, 10))


@pytest.mark.asyncio
async def test_stores_none_on_lookup_failure():
    enrichment_port = AsyncMock()
    enrichment_port.lookup = AsyncMock(side_effect=Exception("network error"))
    ports = MagicMock()
    ports.enrichment = enrichment_port

    state = {"message": "정처기 시험 있어", "today": date(2026, 6, 10)}
    result = await enrichment_node(state, _config(ports))

    assert result["enrichment_context"] is None
    assert result["enrichment_done"] is True
