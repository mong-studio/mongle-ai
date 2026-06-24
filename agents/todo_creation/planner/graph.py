from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.planner.nodes.critic import critic_node, route_after_critic
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
    g.add_node(
        "critic",
        critic_node,
        retry=RetryPolicy(max_attempts=3, retry_on=LLMFailedError),
    )
    g.add_node("out_of_scope", out_of_scope_node)

    g.add_edge(START, "validate")
    g.add_edge("validate", "planner")
    # follow_up resumes after interrupt() and returns to planner for re-evaluation
    g.add_edge("follow_up", "planner")
    # 생성된 plan 은 critic 으로 → major 면 plan_generator 로 재생성, 아니면 END
    # (공식 LangGraph reflection 패턴: 조건부 엣지 + critique_retries 카운터).
    g.add_edge("plan_generator", "critic")
    g.add_conditional_edges(
        "critic",
        route_after_critic,
        {"plan_generator": "plan_generator", END: END},
    )
    g.add_edge("out_of_scope", END)

    return g.compile(checkpointer=_checkpointer)
