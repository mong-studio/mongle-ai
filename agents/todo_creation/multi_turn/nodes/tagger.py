from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState


async def tagger_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    tagged = await ports.llm.tag_plan(
        plan_draft=state["plan_draft"], parsed_goal=state["parsed_goal"],
    )
    return {"current_plan": tagged}
