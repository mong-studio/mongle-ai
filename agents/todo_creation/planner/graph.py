from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.planner.nodes.enrichment import enrichment_node
from agents.todo_creation.planner.nodes.follow_up import follow_up_node
from agents.todo_creation.planner.nodes.out_of_scope import out_of_scope_node
from agents.todo_creation.planner.nodes.plan_generator import plan_generator_node
from agents.todo_creation.planner.nodes.planner import planner_node
from agents.todo_creation.planner.nodes.validate import multi_validate_node
from agents.todo_creation.planner.state import PlannerGraphState

_checkpointer = MemorySaver()


def build_planner_graph():
    g = StateGraph(PlannerGraphState)

    g.add_node("validate", multi_validate_node)
    g.add_node("enrichment", enrichment_node)
    g.add_node(
        "planner",
        planner_node,
        retry=RetryPolicy(max_attempts=3, retry_on=LLMFailedError),
        destinations=("plan_generator", "follow_up", "out_of_scope"),
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
    g.add_node("out_of_scope", out_of_scope_node)

    g.add_edge(START, "validate")
    g.add_edge("validate", "enrichment")
    g.add_edge("enrichment", "planner")
    # follow_up resumes after interrupt() and returns to planner for re-evaluation
    g.add_edge("follow_up", "planner")
    g.add_edge("plan_generator", END)
    g.add_edge("out_of_scope", END)

    return g.compile(checkpointer=_checkpointer)
