from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from agents.todo_creation.schemas import SessionState


@dataclass
class InMemorySessionStore:
    """In-memory SessionStorePort implementation for tests/dev. Single asyncio.Lock."""

    _by_id: dict[str, SessionState] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def load(self, *, session_id: str) -> SessionState | None:
        async with self._lock:
            return self._by_id.get(session_id)

    async def save(self, *, state: SessionState) -> None:
        async with self._lock:
            self._by_id[state.session_id] = state

    async def delete(self, *, session_id: str) -> None:
        async with self._lock:
            self._by_id.pop(session_id, None)
