from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.schemas import ChatMessage


async def phase_router_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    input_ = state["input"]
    loaded = await ports.session_store.load(session_id=input_.session_id)

    if loaded is None:
        phase = "gathering"
        history: list[ChatMessage] = []
        parsed_goal = None
        current_plan = None
    else:
        phase = loaded.phase
        history = list(loaded.history)
        parsed_goal = loaded.parsed_goal
        current_plan = loaded.current_plan

    history.append(ChatMessage(role="user", content=input_.message))
    return {"phase": phase, "history": history, "parsed_goal": parsed_goal, "current_plan": current_plan}


def route_after_phase_router(state: MultiTurnGraphState) -> str:
    return "planner_judge" if state["phase"] == "gathering" else "edit_agent"
