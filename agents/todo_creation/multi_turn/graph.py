from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.multi_turn.nodes.commit_invoke import commit_invoke_node
from agents.todo_creation.multi_turn.nodes.edit_agent import (
    edit_agent_node, route_after_edit_agent,
)
from agents.todo_creation.multi_turn.nodes.follow_up import follow_up_node
from agents.todo_creation.multi_turn.nodes.phase_router import (
    phase_router_node, route_after_phase_router,
)
from agents.todo_creation.multi_turn.nodes.plan_generator import plan_generator_node
from agents.todo_creation.multi_turn.nodes.planner_judge import (
    planner_judge_node, route_after_judge,
)
from agents.todo_creation.multi_turn.nodes.present import present_node
from agents.todo_creation.multi_turn.nodes.tagger import tagger_node
from agents.todo_creation.multi_turn.nodes.validate import validate_node
from agents.todo_creation.multi_turn.state import MultiTurnGraphState


def build_multi_turn_graph():
    g = StateGraph(MultiTurnGraphState)

    g.add_node("validate", validate_node)
    g.add_node("phase_router", phase_router_node)
    g.add_node("planner_judge", planner_judge_node, retry=RetryPolicy(max_attempts=2, retry_on=(LLMFailedError,)))
    g.add_node("follow_up", follow_up_node, retry=RetryPolicy(max_attempts=2, retry_on=(LLMFailedError,)))
    g.add_node("plan_generator", plan_generator_node, retry=RetryPolicy(max_attempts=2, retry_on=(LLMFailedError,)))
    g.add_node("tagger", tagger_node, retry=RetryPolicy(max_attempts=2, retry_on=(LLMFailedError,)))
    g.add_node("edit_agent", edit_agent_node, retry=RetryPolicy(max_attempts=1, retry_on=(LLMFailedError,)))
    g.add_node("commit_invoke", commit_invoke_node)
    g.add_node("present", present_node)

    g.add_edge(START, "validate")
    g.add_edge("validate", "phase_router")
    g.add_conditional_edges(
        "phase_router", route_after_phase_router,
        {"planner_judge": "planner_judge", "edit_agent": "edit_agent"},
    )
    g.add_conditional_edges(
        "planner_judge", route_after_judge,
        {"plan_generator": "plan_generator", "follow_up": "follow_up"},
    )
    g.add_edge("follow_up", "present")
    g.add_edge("plan_generator", "tagger")
    g.add_edge("tagger", "present")
    g.add_conditional_edges(
        "edit_agent", route_after_edit_agent,
        {"plan_generator": "plan_generator", "commit_invoke": "commit_invoke"},
    )
    g.add_edge("commit_invoke", "present")
    g.add_edge("present", END)

    return g.compile()
