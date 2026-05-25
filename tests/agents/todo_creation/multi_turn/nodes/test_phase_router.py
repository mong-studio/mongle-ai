from __future__ import annotations

from datetime import datetime

import pytest

from agents.todo_creation.multi_turn.nodes.phase_router import (
    phase_router_node, route_after_phase_router,
)
from agents.todo_creation.schemas import ChatMessage, ParsedGoal, SessionState


class _Ports:
    def __init__(self, session_store):
        self.session_store = session_store


def _config(session_store):
    return {"configurable": {"ports": _Ports(session_store=session_store)}}


@pytest.mark.asyncio
async def test_new_session_starts_gathering(base_input, session_store):
    out = await phase_router_node({"input": base_input}, _config(session_store))
    assert out["phase"] == "gathering"
    assert out["parsed_goal"] is None and out["current_plan"] is None
    assert len(out["history"]) == 1 and out["history"][0].role == "user"


@pytest.mark.asyncio
async def test_existing_gathering_session_loads(base_input, session_store):
    now = datetime(2026, 5, 25, 11, 0)
    await session_store.save(state=SessionState(
        session_id=base_input.session_id, user_id=base_input.user_id, phase="gathering",
        history=[ChatMessage(role="user", content="이전")], parsed_goal=ParsedGoal(goal_type="X"),
        current_plan=None, created_at=now, updated_at=now,
    ))
    out = await phase_router_node({"input": base_input}, _config(session_store))
    assert out["phase"] == "gathering"
    assert out["parsed_goal"].goal_type == "X"
    assert len(out["history"]) == 2


@pytest.mark.asyncio
async def test_reviewing_session_loads(base_input, session_store):
    now = datetime(2026, 5, 25, 11, 0)
    await session_store.save(state=SessionState(
        session_id=base_input.session_id, user_id=base_input.user_id, phase="reviewing",
        history=[], parsed_goal=ParsedGoal(), current_plan=None,
        created_at=now, updated_at=now,
    ))
    out = await phase_router_node({"input": base_input}, _config(session_store))
    assert out["phase"] == "reviewing"


def test_route_after_phase_router():
    assert route_after_phase_router({"phase": "gathering"}) == "planner_judge"
    assert route_after_phase_router({"phase": "reviewing"}) == "edit_agent"
