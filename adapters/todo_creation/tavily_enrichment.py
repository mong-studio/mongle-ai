"""Tavily 검색 API 를 사용하는 EnrichmentPort 구현체.

TAVILY_API_KEY 환경변수가 설정된 경우에만 PlannerPorts 에 주입된다.
주입되지 않으면 enrichment_node 가 조용히 건너뛴다.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

log = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT = 8.0


class TavilyEnrichment:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def lookup(self, *, keyword: str, today: date) -> dict | None:
        # TODO: Tavily 보다 정확성을 위해서 공식 사이트를 들고 오는 것도 괜찮을듯?
        # - 대신에 docs도 읽어보기

        query = f"{keyword} {today.year} 시험 일정 필기 실기"
        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": 3,
            "include_answer": True,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_TAVILY_URL, json=payload)
            resp.raise_for_status()

        data = resp.json()
        results: list[dict] = data.get("results") or []
        if not results:
            return None

        snippets = [r.get("content", "")[:400] for r in results[:3]]
        return {
            "keyword": keyword,
            "year": today.year,
            "answer": data.get("answer"),
            "snippets": snippets,
        }
