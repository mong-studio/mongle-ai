from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.todo_creation.debug import log_end, log_start, log_step
from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.protocols import LLMPort
from agents.todo_creation.schemas import CandidatesResult, OutOfScopeResult, TodoInput
from agents.todo_creation.todo.nodes.date_router import date_router_node
from agents.todo_creation.todo.nodes.out_of_scope import out_of_scope_node
from agents.todo_creation.todo.nodes.task_splitter import task_splitter_node
from agents.todo_creation.todo.nodes.validate import validate_node
from agents.todo_creation.todo.state import GenerateGraphState


@dataclass
class GeneratePorts:
    llm: LLMPort


def _route_after_split(state: GenerateGraphState) -> str:
    return "out_of_scope" if state.get("intent") == "out_of_scope" else "date_router"


def build_generate_graph():
    g = StateGraph(GenerateGraphState)

    g.add_node("validate", validate_node)
    g.add_node(
        "task_splitter",
        task_splitter_node,
        retry=RetryPolicy(max_attempts=3, retry_on=(LLMFailedError,)),
    )
    g.add_node("date_router", date_router_node)
    g.add_node("out_of_scope", out_of_scope_node)

    g.add_edge(START, "validate")
    g.add_edge("validate", "task_splitter")
    g.add_conditional_edges("task_splitter", _route_after_split, ["date_router", "out_of_scope"])
    g.add_edge("date_router", END)
    g.add_edge("out_of_scope", END)

    return g.compile()


_GRAPH = build_generate_graph()


async def run(
    input: TodoInput,
    *,
    ports: GeneratePorts,
    now: datetime,
) -> CandidatesResult | OutOfScopeResult:
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
