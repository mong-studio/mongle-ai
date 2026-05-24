from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agents.todo_creation.debug import log_end, log_start, log_step
from agents.todo_creation.protocols import LLMPort
from agents.todo_creation.schemas import GenerateResult, SingleTurnInput
from agents.todo_creation.single_turn.graph import build_generate_graph
from agents.todo_creation.single_turn.state import GenerateGraphState


@dataclass
class GeneratePorts:
    llm: LLMPort


_GRAPH = build_generate_graph()


async def run(
    input: SingleTurnInput,
    *,
    ports: GeneratePorts,
    now: datetime,
) -> GenerateResult:
    initial: GenerateGraphState = {"input": input, "now": now}
    config = {"configurable": {"ports": ports, "now": now}}

    log_start(input, "generate")

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

    log_end(final)

    assert final is not None
    result = final["result"]
    assert result is not None
    return result
