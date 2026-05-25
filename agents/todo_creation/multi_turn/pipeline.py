from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.debug import (
    log_end, log_start, log_step, log_turn_input, log_turn_output,
)
from agents.todo_creation.multi_turn.graph import build_multi_turn_graph
from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.protocols import MultiTurnLLMPort, SessionStorePort
from agents.todo_creation.schemas import MultiTurnInput, TurnResult


@dataclass
class MultiTurnPorts:
    llm: MultiTurnLLMPort
    session_store: SessionStorePort
    commit_ports: CommitPorts


_GRAPH = build_multi_turn_graph()


async def run_turn(
    input: MultiTurnInput,
    *,
    ports: MultiTurnPorts,
    now: datetime,
) -> TurnResult:
    initial: MultiTurnGraphState = {"input": input, "now": now}
    config = {"configurable": {"ports": ports, "now": now}}

    log_start(input, "multi_turn")
    log_turn_input(input.message)

    final: Any = None
    step = 0
    async for mode, chunk in _GRAPH.astream(
        initial, config=config, stream_mode=["updates", "values"]
    ):
        if mode == "updates":
            for node_name, update in chunk.items():
                step += 1
                log_step(step, node_name, update)
        elif mode == "values":
            final = chunk

    assert final is not None
    result = final.get("result")
    assert result is not None

    log_turn_output(result)
    log_end(final)

    return result
