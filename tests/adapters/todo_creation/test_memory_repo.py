from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from adapters.todo_creation.memory_repo import MemoryTodoRepository
from agents.todo_creation.exceptions import SaveFailedError
from agents.todo_creation.schemas import TaskCandidate


def _t(title: str = "할 일", d: date = date(2026, 5, 24)) -> TaskCandidate:
    return TaskCandidate(title=title, due_date=d)


async def test_save_returns_ids_for_each_item() -> None:
    repo = MemoryTodoRepository()
    todo_ids, event_ids = await repo.save(
        user_id="u1",
        idempotency_key=uuid4(),
        todos=[_t("a"), _t("b")],
        events=[_t("c", date(2026, 5, 25))],
    )
    assert len(todo_ids) == 2
    assert len(event_ids) == 1
    assert len(set(todo_ids + event_ids)) == 3  # all unique


async def test_find_by_idempotency_key_miss() -> None:
    repo = MemoryTodoRepository()
    result = await repo.find_by_idempotency_key(user_id="u1", key=uuid4())
    assert result is None


async def test_find_by_idempotency_key_hit_after_save() -> None:
    repo = MemoryTodoRepository()
    key = uuid4()
    todo_ids, event_ids = await repo.save(
        user_id="u1",
        idempotency_key=key,
        todos=[_t("a")],
        events=[],
    )
    result = await repo.find_by_idempotency_key(user_id="u1", key=key)
    assert result is not None
    assert result.todo_ids == todo_ids
    assert result.event_ids == event_ids
    assert result.quest_distribution_triggered is False


async def test_save_with_same_key_raises_save_failed_error() -> None:
    repo = MemoryTodoRepository()
    key = uuid4()
    await repo.save(user_id="u1", idempotency_key=key, todos=[_t()], events=[])
    with pytest.raises(SaveFailedError):
        await repo.save(user_id="u1", idempotency_key=key, todos=[_t()], events=[])


async def test_save_failure_simulation() -> None:
    repo = MemoryTodoRepository(fail_next=True)
    with pytest.raises(SaveFailedError):
        await repo.save(
            user_id="u1", idempotency_key=uuid4(), todos=[_t()], events=[]
        )
