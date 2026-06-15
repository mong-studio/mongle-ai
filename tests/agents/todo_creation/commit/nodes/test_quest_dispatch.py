from __future__ import annotations

from datetime import date
from uuid import uuid4

from agents.todo_creation.commit.nodes.quest_dispatch import quest_dispatch_node
from agents.todo_creation.schemas import CommitPayload, TaskCandidate


class _SuccessPort:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def dispatch(self, *, user_id: str) -> None:
        self.calls.append(user_id)


class _FailingPort:
    async def dispatch(self, *, user_id: str) -> None:
        raise RuntimeError("simulated dispatch failure")


def _state_and_ports(port) -> tuple[dict, dict]:
    inp = CommitPayload(
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


async def test_quest_dispatch_success_sets_triggered_true() -> None:
    port = _SuccessPort()
    state, config = _state_and_ports(port)
    diff = await quest_dispatch_node(state, config)
    assert diff["quest_triggered"] is True
    assert port.calls == ["u1"]


async def test_quest_dispatch_failure_is_silently_skipped() -> None:
    state, config = _state_and_ports(_FailingPort())
    diff = await quest_dispatch_node(state, config)
    assert diff["quest_triggered"] is False
