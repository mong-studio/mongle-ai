from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.single_turn.nodes.date_router import date_router_node
from agents.todo_creation.single_turn.nodes.task_splitter import task_splitter_node
from agents.todo_creation.single_turn.nodes.validate import validate_node
from agents.todo_creation.single_turn.state import GenerateGraphState


def build_generate_graph():
    g = StateGraph(GenerateGraphState)

    g.add_node("validate", validate_node)
    g.add_node(
        "task_splitter",
        task_splitter_node,
        retry=RetryPolicy(max_attempts=3, retry_on=(LLMFailedError,)),
    )
    g.add_node("date_router", date_router_node)

    g.add_edge(START, "validate")
    g.add_edge("validate", "task_splitter")
    g.add_edge("task_splitter", "date_router")
    g.add_edge("date_router", END)

    return g.compile()
