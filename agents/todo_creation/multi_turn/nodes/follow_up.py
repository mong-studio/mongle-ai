from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState


async def follow_up_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    question = await ports.llm.generate_follow_up(
        missing_aspects=state["judgment"].missing_aspects,
        history=state["history"],
    )
    return {"follow_up_question": question}
