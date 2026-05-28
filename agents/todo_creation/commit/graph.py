from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.todo_creation.commit.nodes.quest_dispatch import quest_dispatch_node
from agents.todo_creation.commit.nodes.quest_gate import quest_gate
from agents.todo_creation.commit.nodes.quota_restore import quota_restore_node
from agents.todo_creation.commit.nodes.save_dispatcher import save_dispatcher_node
from agents.todo_creation.commit.nodes.validate import validate_node
from agents.todo_creation.commit.state import CommitGraphState


def build_commit_graph():
    g = StateGraph(CommitGraphState)

    g.add_node("validate", validate_node)
    g.add_node("save_dispatcher", save_dispatcher_node)
    g.add_node(
        "quest_dispatch",
        quest_dispatch_node,
        destinations=("quota_restore", END),
    )
    g.add_node("quota_restore", quota_restore_node)

    g.add_edge(START, "validate")
    g.add_edge("validate", "save_dispatcher")
    g.add_conditional_edges(
        "save_dispatcher",
        quest_gate,
        ["quest_dispatch", END],
    )
    g.add_edge("quota_restore", END)

    return g.compile()
