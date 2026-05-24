from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

import pytest

from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from agents.todo_creation.commit.pipeline import CommitPorts, run
from agents.todo_creation.exceptions import SaveFailedError
from agents.todo_creation.schemas import CommitInput, TaskCandidate


class _Dispatch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def dispatch(self, *, user_id: str) -> None:
        self.calls.append(user_id)


def _input() -> CommitInput:
    return CommitInput(
        user_id="u1",
        idempotency_key=uuid4(),
        today=date(2026, 5, 24),
        todos=[TaskCandidate(title="오늘", due_date=date(2026, 5, 24))],
        calendar_events=[],
    )


async def test_pipeline_returns_commit_result() -> None:
    ports = CommitPorts(
        repository=MemoryTodoRepository(),
        quest_counter=MemoryQuestCounter(),
        quest_dispatch=_Dispatch(),
    )
    result = await run(
        _input(), ports=ports, now=datetime(2026, 5, 24, 12, 0)
    )
    assert len(result.todo_ids) == 1
    assert result.event_ids == []
    assert result.quest_distribution_triggered is True


async def test_pipeline_raises_on_save_failure() -> None:
    ports = CommitPorts(
        repository=MemoryTodoRepository(fail_next=True),
        quest_counter=MemoryQuestCounter(),
        quest_dispatch=_Dispatch(),
    )
    with pytest.raises(SaveFailedError):
        await run(_input(), ports=ports, now=datetime(2026, 5, 24, 12, 0))
