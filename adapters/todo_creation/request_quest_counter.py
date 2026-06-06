from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class RequestQuestCounter:
    """QuestCounterPort 의 request-backed 구현.

    Django 가 보낸 remaining_daily_quota 만으로 트리거 여부를 판정한다.
    commit 그래프는 요청당 quest_gate 에서 단 한 번 호출하므로,
    남은 쿼터가 1 이상이면 허용한다. (전달된 limit 인자는 무시 — 진짜
    한도는 Django 가 소유, 본 서비스는 무상태.)
    """

    remaining: int

    async def incr_if_under_limit(
        self, *, user_id: str, day_kst: date, limit: int
    ) -> bool:
        return self.remaining > 0
