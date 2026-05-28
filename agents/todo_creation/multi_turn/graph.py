from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.multi_turn.nodes.follow_up import follow_up_node
from agents.todo_creation.multi_turn.nodes.plan_generator import plan_generator_node
from agents.todo_creation.multi_turn.nodes.planner import planner_node
from agents.todo_creation.multi_turn.nodes.validate import multi_validate_node
from agents.todo_creation.multi_turn.state import MultiTurnGraphState

_checkpointer = MemorySaver()


def build_multi_turn_graph():
    g = StateGraph(MultiTurnGraphState)

    g.add_node("validate", multi_validate_node)
    g.add_node(
        "planner",
        planner_node,
        retry=RetryPolicy(max_attempts=3, retry_on=LLMFailedError),
        destinations=("plan_generator", "follow_up"),
    )
    g.add_node(
        "follow_up",
        follow_up_node,
        retry=RetryPolicy(max_attempts=3, retry_on=LLMFailedError),
    )
    g.add_node(
        "plan_generator",
        plan_generator_node,
        retry=RetryPolicy(max_attempts=3, retry_on=LLMFailedError),
    )

    g.add_edge(START, "validate")
    g.add_edge("validate", "planner")
    # follow_up resumes after interrupt() and returns to planner for re-evaluation
    g.add_edge("follow_up", "planner")
    g.add_edge("plan_generator", END)

    return g.compile(checkpointer=_checkpointer)
