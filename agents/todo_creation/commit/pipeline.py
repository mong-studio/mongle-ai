from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agents.todo_creation.commit.graph import build_commit_graph
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
