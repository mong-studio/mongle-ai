from datetime import date

import pytest

from adapters.todo_creation.request_quest_counter import RequestQuestCounter


@pytest.mark.asyncio
async def test_allows_when_remaining_positive():
    counter = RequestQuestCounter(remaining=2)
    assert await counter.incr_if_under_limit(
        user_id="u1", day_kst=date(2026, 6, 4), limit=5
    ) is True


@pytest.mark.asyncio
async def test_blocks_when_no_remaining():
    counter = RequestQuestCounter(remaining=0)
    assert await counter.incr_if_under_limit(
        user_id="u1", day_kst=date(2026, 6, 4), limit=5
    ) is False
