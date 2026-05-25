from __future__ import annotations

from typing import Any

from agents.todo_creation.exceptions import EditAgentError
from agents.todo_creation.multi_turn.state import MultiTurnGraphState


async def edit_agent_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    decision = await ports.llm.edit_agent_step(
        history=state["history"], current_plan=state["current_plan"],
    )

    if decision.tool_name == "confirm":
        return {"confirmed": True}

    if decision.tool_name == "regenerate_plan":
        instructions = decision.tool_args.get("instructions")
        if not instructions:
            raise EditAgentError(code="M9", message="regenerate_plan called without instructions")
        return {"edit_instructions": instructions}

    raise EditAgentError(code="M9", message=f"unknown tool: {decision.tool_name}")


def route_after_edit_agent(state: MultiTurnGraphState) -> str:
    if state.get("confirmed"):
        return "commit_invoke"
    if state.get("edit_instructions"):
        return "plan_generator"
    raise EditAgentError(code="M9", message="edit_agent produced no decision")
