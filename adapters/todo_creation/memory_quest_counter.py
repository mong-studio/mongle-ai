from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date


@dataclass
class MemoryQuestCounter:
    """In-memory QuestCounterPort. `incr_if_under_limit` is atomic via asyncio.Lock."""

    _counts: dict[tuple[str, date], int] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def incr_if_under_limit(
        self, *, user_id: str, day_kst: date, limit: int
    ) -> bool:
        async with self._lock:
            current = self._counts.get((user_id, day_kst), 0)
            if current >= limit:
                return False
            self._counts[(user_id, day_kst)] = current + 1
            return True

    async def decr(self, *, user_id: str, day_kst: date) -> None:
        async with self._lock:
            current = self._counts.get((user_id, day_kst), 0)
            if current > 0:
                self._counts[(user_id, day_kst)] = current - 1

    def peek(self, *, user_id: str, day_kst: date) -> int:
        return self._counts.get((user_id, day_kst), 0)
