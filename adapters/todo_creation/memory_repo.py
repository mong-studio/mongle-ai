from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from agents.todo_creation.exceptions import SaveFailedError
from agents.todo_creation.schemas import CommitResult, TaskCandidate


@dataclass
class _Stored:
    todos: list[tuple[UUID, TaskCandidate]] = field(default_factory=list)
    events: list[tuple[UUID, TaskCandidate]] = field(default_factory=list)


@dataclass
class MemoryTodoRepository:
    """In-memory TodoRepositoryPort implementation for tests.

    - Single transaction by `asyncio.Lock` (no partial save).
    - Idempotency key is unique per (user_id, key) — second save with same key raises.
    - `fail_next`: simulate DB failure on the next `save` call (auto-resets after raise).
    """

    fail_next: bool = False
    _by_user: dict[str, _Stored] = field(default_factory=dict)
    _by_idem: dict[tuple[str, UUID], CommitResult] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def find_by_idempotency_key(
        self, *, user_id: str, key: UUID
    ) -> CommitResult | None:
        async with self._lock:
            return self._by_idem.get((user_id, key))

    async def save(
        self,
        *,
        user_id: str,
        idempotency_key: UUID,
        todos: list[TaskCandidate],
        events: list[TaskCandidate],
    ) -> tuple[list[UUID], list[UUID]]:
        async with self._lock:
            if self.fail_next:
                self.fail_next = False
                raise SaveFailedError("simulated DB failure")
            if (user_id, idempotency_key) in self._by_idem:
                raise SaveFailedError("duplicate idempotency_key")

            store = self._by_user.setdefault(user_id, _Stored())
            todo_ids = [uuid4() for _ in todos]
            event_ids = [uuid4() for _ in events]
            store.todos.extend(zip(todo_ids, todos))
            store.events.extend(zip(event_ids, events))

            self._by_idem[(user_id, idempotency_key)] = CommitResult(
                todo_ids=todo_ids,
                event_ids=event_ids,
                quest_distribution_triggered=False,
            )
            return todo_ids, event_ids
