from __future__ import annotations

import asyncio
from datetime import date

from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter


async def test_incr_under_limit_returns_true_and_increments() -> None:
    c = MemoryQuestCounter()
    ok = await c.incr_if_under_limit(
        user_id="u1", day_kst=date(2026, 5, 24), limit=5
    )
    assert ok is True
    assert c.peek(user_id="u1", day_kst=date(2026, 5, 24)) == 1


async def test_incr_at_limit_returns_false_without_increment() -> None:
    c = MemoryQuestCounter()
    for _ in range(5):
        assert await c.incr_if_under_limit(
            user_id="u1", day_kst=date(2026, 5, 24), limit=5
        )
    ok = await c.incr_if_under_limit(
        user_id="u1", day_kst=date(2026, 5, 24), limit=5
    )
    assert ok is False
    assert c.peek(user_id="u1", day_kst=date(2026, 5, 24)) == 5


async def test_per_user_per_day_isolation() -> None:
    c = MemoryQuestCounter()
    await c.incr_if_under_limit(user_id="u1", day_kst=date(2026, 5, 24), limit=5)
    assert c.peek(user_id="u2", day_kst=date(2026, 5, 24)) == 0
    assert c.peek(user_id="u1", day_kst=date(2026, 5, 25)) == 0


async def test_concurrent_increments_atomic() -> None:
    c = MemoryQuestCounter()

    async def attempt() -> bool:
        return await c.incr_if_under_limit(
            user_id="u1", day_kst=date(2026, 5, 24), limit=5
        )

    results = await asyncio.gather(*(attempt() for _ in range(20)))
    true_count = sum(1 for r in results if r is True)
    assert true_count == 5
    assert c.peek(user_id="u1", day_kst=date(2026, 5, 24)) == 5
