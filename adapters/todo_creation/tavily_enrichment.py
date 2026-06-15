"""Tavily 검색 API 를 사용하는 EnrichmentPort 구현체.

TAVILY_API_KEY 환경변수가 설정된 경우에만 PlannerPorts 에 주입된다.
주입되지 않으면 enrichment_node 가 조용히 건너뛴다.
검색 텍스트(answer+results)에서 date_extract 로 시험일을 구조화해 돌려준다.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

from adapters.todo_creation.date_extract import extract_exam_dates

log = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT = 8.0

# 시험별 공식 도메인 화이트리스트(정확도↑). 모르는 키워드는 일반 검색으로 폴백.
_QNET = ("q-net.or.kr",)
_OFFICIAL_DOMAINS: dict[str, tuple[str, ...]] = {
    "정보처리기사": _QNET,
    "정보처리산업기사": _QNET,
    "전기기사": _QNET,
    "전기산업기사": _QNET,
    "소방설비기사": _QNET,
    "건축기사": _QNET,
    "공인중개사": _QNET,
    "변리사": _QNET,
    "사회복지사": _QNET,
    "컴퓨터활용능력": ("license.korcham.net",),
    "한국사능력검정시험": ("history.go.kr",),
    "TOEIC": ("toeic.co.kr",),
    "TOEFL": ("ets.org",),
}


class TavilyEnrichment:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def lookup(self, *, keyword: str, today: date) -> dict | None:
        query = f"{keyword} {today.year} 시험 일정 필기 실기"
        payload: dict = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": 5,
            "include_answer": "advanced",
        }
        domains = _OFFICIAL_DOMAINS.get(keyword)
        if domains:
            payload["include_domains"] = list(domains)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_TAVILY_URL, json=payload)
            resp.raise_for_status()

        data = resp.json()
        results: list[dict] = data.get("results") or []
        if not results:
            return None

        answer = data.get("answer")
        snippets = [r.get("content", "")[:400] for r in results[:3]]

        combined = " ".join(
            [str(answer or ""), *[str(r.get("content", "")) for r in results]]
        )
        candidates = extract_exam_dates(combined, today=today)
        exam_dates = [
            {"date": c.date.isoformat(), "part": c.part} for c in candidates
        ]
        suggested_deadline = exam_dates[0]["date"] if exam_dates else None

        return {
            "keyword": keyword,
            "year": today.year,
            "answer": answer,
            "snippets": snippets,
            "exam_dates": exam_dates,
            "suggested_deadline": suggested_deadline,
        }
