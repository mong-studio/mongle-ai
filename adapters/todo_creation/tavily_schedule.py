"""Tavily 백엔드 시험일 해석 어댑터
ExamScheduleLookupPort 구현. 비용 튜닝: search_depth="basic"(1크레딧, advanced 2배 불필요 —
include_domains 핀 + 상위 폴백이 안전망). include_domains/start_date/include_answer/country 는
크레딧 무료라 정밀도·파싱 이득만 취한다. tavily-python SDK 는 sync 라 asyncio.to_thread 로 감싼다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

from agents.todo_creation.planner.schedule_lookup import parse_future_date

log = logging.getLogger(__name__)

# ponytail: 프로세스-수명 캐시(성공 날짜만). 시험일은 연내 안정적이라 (exam_name, year) 로 충분.
# TTL 없음 — 일정이 갱신될 만큼 장수명 프로세스면 재기동 시 비워진다(서버리스는 자연 초기화).
_CACHE: dict[tuple[str, int], date] = {}


@dataclass
class TavilyExamScheduleLookup:
    """공식 도메인으로 핀한 Tavily basic 검색으로 다음 시험일을 가져온다."""

    api_key: str

    async def next_exam_date(
        self, *, exam_name: str, official_domains: list[str], today: date
    ) -> date | None:
        cache_key = (exam_name, today.year)
        cached = _CACHE.get(cache_key)
        if cached is not None and cached > today:
            return cached  # 유료 호출 절약(성공분만 캐시)
        try:
            from tavily import TavilyClient  # lazy: tavily 미설치 시 import 비용 0
        except ImportError:
            log.warning("tavily-python 미설치 — 시험일 해석 건너뜀(되묻기 폴백)")
            return None

        client = TavilyClient(api_key=self.api_key)
        try:
            resp = await asyncio.to_thread(
                client.search,
                query=f"{exam_name} {today.year} 시험 일정",
                search_depth="basic",
                include_domains=official_domains,
                start_date=today.isoformat(),
                include_answer="basic",
                country="south korea",
                max_results=3,
            )
        except Exception as err:  # noqa: BLE001 - 네트워크/API 실패는 되묻기로 폴백
            log.warning("tavily search failed for %s: %s", exam_name, err)
            return None

        answer = str(resp.get("answer") or "")
        contents = " ".join(
            str(r.get("content") or "") for r in resp.get("results") or []
        )
        resolved = parse_future_date(f"{answer} {contents}", today=today)
        if resolved is not None:
            _CACHE[cache_key] = resolved
        return resolved
