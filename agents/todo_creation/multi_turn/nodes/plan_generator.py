from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState


async def plan_generator_node(
    state: MultiTurnGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    llm = ports.llm
    parsed_goal = state.get("parsed_goal") or {}
    today = state["today"]

    summary_text, plan = await llm.generate_plan(parsed_goal=parsed_goal, today=today)
    tagged_plan = await llm.tag_plan(plan=plan, parsed_goal=parsed_goal)

    todos = []
    calendar_events = []
    for day in tagged_plan:
        for task in day.get("tasks", []):
            if task.due_date == today:
                todos.append(task)
            else:
                calendar_events.append(task)

    return {
        "summary_text": summary_text,
        "plan": tagged_plan,
        "todos": todos,
        "calendar_events": calendar_events,
    }
