from __future__ import annotations

from datetime import datetime

import pytest

from agents.todo_creation.multi_turn.session_store import InMemorySessionStore
from agents.todo_creation.schemas import SessionState


def _state(session_id: str = "s1") -> SessionState:
    now = datetime(2026, 5, 25, 12, 0)
    return SessionState(
        session_id=session_id, user_id="u1", phase="gathering", history=[],
        parsed_goal=None, current_plan=None, created_at=now, updated_at=now,
    )


@pytest.mark.asyncio
async def test_load_returns_none_when_missing():
    store = InMemorySessionStore()
    assert await store.load(session_id="nope") is None


@pytest.mark.asyncio
async def test_save_then_load_roundtrip():
    store = InMemorySessionStore()
    await store.save(state=_state())
    loaded = await store.load(session_id="s1")
    assert loaded is not None and loaded.phase == "gathering"


@pytest.mark.asyncio
async def test_save_is_upsert():
    store = InMemorySessionStore()
    s = _state()
    await store.save(state=s)
    await store.save(state=s.model_copy(update={"phase": "reviewing"}))
    loaded = await store.load(session_id="s1")
    assert loaded.phase == "reviewing"


@pytest.mark.asyncio
async def test_delete_removes():
    store = InMemorySessionStore()
    await store.save(state=_state())
    await store.delete(session_id="s1")
    assert await store.load(session_id="s1") is None


@pytest.mark.asyncio
async def test_delete_missing_is_idempotent():
    store = InMemorySessionStore()
    await store.delete(session_id="nope")
