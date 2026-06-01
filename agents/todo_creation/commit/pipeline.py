from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.todo_creation.commit.nodes.quest_dispatch import quest_dispatch_node
from agents.todo_creation.commit.nodes.quest_gate import quest_gate
from agents.todo_creation.commit.nodes.save_dispatcher import save_dispatcher_node
from agents.todo_creation.commit.nodes.validate import validate_node
from agents.todo_creation.commit.state import CommitGraphState
from agents.todo_creation.debug import log_end, log_start, log_step
from agents.todo_creation.protocols import (
    QuestCounterPort,
    QuestDispatchPort,
    TodoRepositoryPort,
)
from agents.todo_creation.schemas import CommitInput, CommitResult


@dataclass
class CommitPorts:
    repository: TodoRepositoryPort
    quest_counter: QuestCounterPort
    quest_dispatch: QuestDispatchPort


def build_commit_graph():
    g = StateGraph(CommitGraphState)

    g.add_node("validate", validate_node)
    g.add_node("save_dispatcher", save_dispatcher_node)
    g.add_node("quest_dispatch", quest_dispatch_node)

    g.add_edge(START, "validate")
    g.add_edge("validate", "save_dispatcher")
    g.add_conditional_edges(
        "save_dispatcher",
        quest_gate,
        ["quest_dispatch", END],
    )
    g.add_edge("quest_dispatch", END)

    return g.compile()


_GRAPH = build_commit_graph()


async def run(
    input: CommitInput,
    *,
    ports: CommitPorts,
    now: datetime,
) -> CommitResult:
    initial: CommitGraphState = {"input": input, "now": now}
    config = {"configurable": {"ports": ports, "now": now}}

    log_start(input, "commit")

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
    return CommitResult(
        todo_ids=final["todo_ids"] or [],
        event_ids=final["event_ids"] or [],
        quest_distribution_triggered=bool(final.get("quest_triggered")),
    )
