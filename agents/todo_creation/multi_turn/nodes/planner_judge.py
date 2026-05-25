from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState


async def planner_judge_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    judgment = await ports.llm.judge_planner(
        history=state["history"],
        previous_goal=state.get("parsed_goal"),
        today=state["input"].today,
    )
    return {"judgment": judgment, "parsed_goal": judgment.parsed_goal}


def route_after_judge(state: MultiTurnGraphState) -> str:
    return "plan_generator" if state["judgment"].is_sufficient else "follow_up"
