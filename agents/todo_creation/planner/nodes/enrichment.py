"""multi 모드 enrichment 노드.

첫 번째 턴에서 메시지 안에 시험/자격증 키워드가 있으면 EnrichmentPort.lookup() 으로
실제 일정을 조회해 state 에 enrichment_context 를 저장한다.
이후 follow_up 노드가 이 context 를 참고해 "필기(7/5) vs 실기(8/17) 중 어느 시험인가요?"
같이 구체적인 날짜가 포함된 질문을 생성한다.

EnrichmentPort 가 없거나 키워드가 없으면 즉시 빈 dict 반환.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.planner.state import PlannerGraphState

log = logging.getLogger(__name__)


def _suggested_deadline(context: dict | None, today: date | None) -> date | None:
    """구조화된 enrichment context 에서 today 이후 가장 가까운 시험일을 고른다."""
    if not isinstance(context, dict) or today is None:
        return None
    raw = context.get("suggested_deadline")
    if isinstance(raw, str):
        try:
            d = date.fromisoformat(raw)
            return d if d >= today else None
        except ValueError:
            pass
    candidates: list[date] = []
    for item in context.get("exam_dates") or []:
        value = item.get("date") if isinstance(item, dict) else None
        if isinstance(value, str):
            try:
                d = date.fromisoformat(value)
            except ValueError:
                continue
            if d >= today:
                candidates.append(d)
    return min(candidates) if candidates else None


# TODO: 하드코딩보다는 이것을 관리해주는 DB
# - 키워드 매핑 시에 질문
_KEYWORD_MAP: dict[str, str] = {
    "정처기": "정보처리기사",
    "정보처리기사": "정보처리기사",
    "정보처리산업기사": "정보처리산업기사",
    "컴활": "컴퓨터활용능력",
    "컴퓨터활용능력": "컴퓨터활용능력",
    "토익": "TOEIC",
    "toeic": "TOEIC",
    "토플": "TOEFL",
    "toefl": "TOEFL",
    "한능검": "한국사능력검정시험",
    "한국사능력검정": "한국사능력검정시험",
    "공인중개사": "공인중개사",
    "전기기사": "전기기사",
    "전기산업기사": "전기산업기사",
    "소방설비기사": "소방설비기사",
    "건축기사": "건축기사",
    "cpa": "공인회계사",
    "공인회계사": "공인회계사",
    "변리사": "변리사",
    "세무사": "세무사",
    "사회복지사": "사회복지사",
}


def _detect_keyword(text: str) -> str | None:
    lower = text.lower()
    for raw, normalized in _KEYWORD_MAP.items():
        if raw in lower:
            return normalized
    return None


async def enrichment_node(
    state: PlannerGraphState, config: RunnableConfig
) -> dict[str, Any]:
    if state.get("enrichment_done"):
        return {}

    combined = " ".join(
        [
            str(state.get("message", "")),
            *[
                str(t.get("content", ""))
                for t in state.get("history", [])
                if t.get("role") == "user"
            ],
        ]
    )
    keyword = _detect_keyword(combined)
    if keyword is None:
        return {"enrichment_done": True}

    ports = get_ports(config)
    enrichment_port = getattr(ports, "enrichment", None)
    if enrichment_port is None:
        return {"enrichment_done": True}

    today = state.get("today")
    try:
        context = await enrichment_port.lookup(keyword=keyword, today=today)
    except Exception:
        log.warning("enrichment lookup failed for keyword=%r", keyword, exc_info=True)
        context = None

    update: dict[str, Any] = {"enrichment_context": context, "enrichment_done": True}
    suggested = _suggested_deadline(context, today)
    if suggested is not None:
        update["suggested_deadline"] = suggested
    return update
