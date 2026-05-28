from __future__ import annotations

from datetime import date
from uuid import uuid4

from langgraph.graph import END
from langgraph.types import Command

from agents.todo_creation.commit.nodes.quest_dispatch import quest_dispatch_node
from agents.todo_creation.schemas import CommitInput, TaskCandidate


class _SuccessPort:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def dispatch(self, *, user_id: str) -> None:
        self.calls.append(user_id)


class _FailingPort:
    async def dispatch(self, *, user_id: str) -> None:
        raise RuntimeError("simulated dispatch failure")


def _state_and_ports(port) -> tuple[dict, dict]:
    inp = CommitInput(
        user_id="u1",
        idempotency_key=uuid4(),
        today=date(2026, 5, 24),
        todos=[TaskCandidate(title="x", due_date=date(2026, 5, 24))],
        calendar_events=[],
    )

    class _P:
        pass

    p = _P()
    p.quest_dispatch = port
    state = {"input": inp, "now": None}
    config = {"configurable": {"ports": p, "now": None}}
    return state, config


async def test_quest_dispatch_success_routes_to_end() -> None:
    port = _SuccessPort()
    state, config = _state_and_ports(port)
    cmd = await quest_dispatch_node(state, config)
    assert isinstance(cmd, Command)
    assert cmd.goto == END
    assert cmd.update["quest_triggered"] is True
    assert port.calls == ["u1"]


async def test_quest_dispatch_failure_routes_to_quota_restore() -> None:
    state, config = _state_and_ports(_FailingPort())
    cmd = await quest_dispatch_node(state, config)
    assert isinstance(cmd, Command)
    assert cmd.goto == "quota_restore"
    assert cmd.update["quest_triggered"] is False
