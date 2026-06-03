from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from agents.todo_creation.multi_turn.graph import build_multi_turn_graph
from agents.todo_creation.protocols import LLMPort
from agents.todo_creation.schemas import (
    FollowUpResult,
    GenerateResult,
    MultiGenerateInput,
    TurnResult,
)


@dataclass
class MultiTurnPorts:
    llm: LLMPort


_GRAPH = build_multi_turn_graph()


async def run(
    input: MultiGenerateInput,
    *,
    ports: MultiTurnPorts,
    now: datetime,
) -> TurnResult:
    thread_id = input.thread_id or str(uuid4())
    config = {"configurable": {"ports": ports, "thread_id": thread_id}}

    graph_input: Any
    if input.thread_id is not None:
        snapshot = _GRAPH.get_state(config)
        if snapshot.next:
            # graph paused at follow_up interrupt — resume with user's answer
            graph_input = Command(resume=input.message)
        else:
            graph_input = _initial_state(input, now)
    else:
        graph_input = _initial_state(input, now)

    interrupt_question: str | None = None
    final: dict[str, Any] = {}

    async for mode, chunk in _GRAPH.astream(
        graph_input, config=config, stream_mode=["updates", "values"]
    ):
        if mode == "updates" and "__interrupt__" in chunk:
            interrupts = chunk["__interrupt__"]
            interrupt_question = interrupts[0].value if interrupts else ""
        elif mode == "values":
            final = chunk

    if interrupt_question is not None:
        state_after = _GRAPH.get_state(config)
        return FollowUpResult(
            thread_id=thread_id,
            question=interrupt_question,
            missing_aspects=state_after.values.get("missing_aspects") or [],
        )

    return GenerateResult(
        thread_id=thread_id,
        todos=final.get("todos") or [],
        calendar_events=final.get("calendar_events") or [],
        summary_text=final.get("summary_text"),
    )


def _initial_state(input: MultiGenerateInput, now: datetime) -> dict[str, Any]:
    return {
        "message": input.message,
        "today": input.today,
        "now": now,
        "user_id": input.user_id,
    }
