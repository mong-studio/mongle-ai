from __future__ import annotations

from datetime import date
from uuid import uuid4

from langgraph.graph import END

from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from agents.todo_creation.commit.nodes.quest_gate import quest_gate
from agents.todo_creation.schemas import CommitInput, TaskCandidate


def _today_task() -> TaskCandidate:
    return TaskCandidate(title="오늘 일", due_date=date(2026, 5, 24))


def _state(
    *,
    re_routed_todos: list[TaskCandidate],
    idempotent_hit: bool,
) -> tuple[dict, dict, MemoryQuestCounter]:
    inp = CommitInput(
        user_id="u1",
        idempotency_key=uuid4(),
        today=date(2026, 5, 24),
        todos=[_today_task()],
        calendar_events=[],
    )
    counter = MemoryQuestCounter()

    class _P:
        pass

    p = _P()
    p.quest_counter = counter
    state = {
        "input": inp,
        "now": None,
        "re_routed_todos": re_routed_todos,
        "re_routed_events": [],
        "idempotent_hit": idempotent_hit,
    }
    config = {"configurable": {"ports": p, "now": None}}
    return state, config, counter


async def test_quest_gate_routes_to_dispatch_on_happy_path() -> None:
    state, config, counter = _state(
        re_routed_todos=[_today_task()], idempotent_hit=False
    )
    next_node = await quest_gate(state, config)
    assert next_node == "quest_dispatch"
    assert counter.peek(user_id="u1", day_kst=date(2026, 5, 24)) == 1


async def test_quest_gate_skips_when_no_today_todos() -> None:
    state, config, counter = _state(re_routed_todos=[], idempotent_hit=False)
    next_node = await quest_gate(state, config)
    assert next_node == END
    assert counter.peek(user_id="u1", day_kst=date(2026, 5, 24)) == 0


async def test_quest_gate_skips_on_idempotent_hit() -> None:
    state, config, counter = _state(
        re_routed_todos=[_today_task()], idempotent_hit=True
    )
    next_node = await quest_gate(state, config)
    assert next_node == END
    assert counter.peek(user_id="u1", day_kst=date(2026, 5, 24)) == 0


async def test_quest_gate_skips_when_quota_exceeded() -> None:
    state, config, counter = _state(
        re_routed_todos=[_today_task()], idempotent_hit=False
    )
    for _ in range(5):
        await counter.incr_if_under_limit(
            user_id="u1", day_kst=date(2026, 5, 24), limit=5
        )
    next_node = await quest_gate(state, config)
    assert next_node == END
    assert counter.peek(user_id="u1", day_kst=date(2026, 5, 24)) == 5
