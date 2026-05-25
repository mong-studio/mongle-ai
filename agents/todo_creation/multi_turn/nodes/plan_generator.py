from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState

C3_LIMIT = 1500


def truncate_at_sentence(text: str, *, limit: int = C3_LIMIT) -> str:
    """Truncate text to <= limit chars, preferring the last sentence boundary."""
    if len(text) <= limit:
        return text
    candidate = text[:limit]
    last_period = candidate.rfind(".")
    if last_period >= 0:
        return candidate[: last_period + 1]
    return candidate


async def plan_generator_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    parsed_goal = state["parsed_goal"]
    today = state["input"].today
    edit_instructions = state.get("edit_instructions")

    draft = await ports.llm.generate_plan(
        parsed_goal=parsed_goal, today=today, edit_instructions=edit_instructions,
    )

    if len(draft.summary_text) > C3_LIMIT:
        retry_instructions = (
            (edit_instructions or "")
            + f"\n[중요] summary_text 는 반드시 {C3_LIMIT}자 이하."
        ).strip()
        draft = await ports.llm.generate_plan(
            parsed_goal=parsed_goal, today=today, edit_instructions=retry_instructions,
        )
        if len(draft.summary_text) > C3_LIMIT:
            draft = draft.model_copy(update={"summary_text": truncate_at_sentence(draft.summary_text)})

    return {"plan_draft": draft, "edit_instructions": None}
