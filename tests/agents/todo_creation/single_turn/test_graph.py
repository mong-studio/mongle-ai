from __future__ import annotations

from datetime import date

import pytest

from adapters.todo_creation.fake_llm import FakeLLM
from agents.todo_creation.exceptions import LLMFailedError, ValidationError
from agents.todo_creation.schemas import SingleTurnInput, TaskCandidate
from agents.todo_creation.single_turn.graph import build_generate_graph


class _Ports:
    def __init__(self, llm: FakeLLM) -> None:
        self.llm = llm


def _state(prompt: str = "오늘 코테") -> dict:
    return {
        "input": SingleTurnInput(
            user_id="u1", prompt=prompt, today=date(2026, 5, 24)
        ),
        "now": None,
    }


async def test_graph_happy_today_only() -> None:
    graph = build_generate_graph()
    llm = FakeLLM(
        responses=[[TaskCandidate(title="코테", due_date=date(2026, 5, 24))]]
    )
    final = await graph.ainvoke(
        _state(),
        config={"configurable": {"ports": _Ports(llm), "now": None}},
    )
    assert len(final["result"].todos) == 1
    assert final["result"].calendar_events == []


async def test_graph_happy_mixed_today_and_future() -> None:
    graph = build_generate_graph()
    llm = FakeLLM(
        responses=[
            [
                TaskCandidate(title="코테", due_date=date(2026, 5, 24)),
                TaskCandidate(title="발표", due_date=date(2026, 5, 27)),
            ]
        ]
    )
    final = await graph.ainvoke(
        _state("오늘 코테, 3일 뒤 발표"),
        config={"configurable": {"ports": _Ports(llm), "now": None}},
    )
    assert len(final["result"].todos) == 1
    assert len(final["result"].calendar_events) == 1


async def test_graph_past_date_silently_corrected() -> None:
    graph = build_generate_graph()
    llm = FakeLLM(
        responses=[[TaskCandidate(title="어제 일", due_date=date(2026, 5, 23))]]
    )
    final = await graph.ainvoke(
        _state(),
        config={"configurable": {"ports": _Ports(llm), "now": None}},
    )
    assert len(final["result"].todos) == 1
    assert final["result"].todos[0].due_date == date(2026, 5, 24)


async def test_graph_rejects_long_prompt() -> None:
    graph = build_generate_graph()
    long_prompt = "가" * 201
    inp = SingleTurnInput.model_construct(
        user_id="u1", prompt=long_prompt, today=date(2026, 5, 24)
    )
    with pytest.raises(ValidationError):
        await graph.ainvoke(
            {"input": inp, "now": None},
            config={
                "configurable": {"ports": _Ports(FakeLLM()), "now": None}
            },
        )


async def test_graph_llm_retry_eventually_succeeds() -> None:
    graph = build_generate_graph()
    llm = FakeLLM(
        fail_times=2,
        responses=[[TaskCandidate(title="코테", due_date=date(2026, 5, 24))]],
    )
    final = await graph.ainvoke(
        _state(),
        config={"configurable": {"ports": _Ports(llm), "now": None}},
    )
    assert len(final["result"].todos) == 1
    assert llm.calls == 3


async def test_graph_llm_completely_failing_raises() -> None:
    graph = build_generate_graph()
    llm = FakeLLM(fail_times=99, responses=[])
    with pytest.raises(LLMFailedError):
        await graph.ainvoke(
            _state(),
            config={"configurable": {"ports": _Ports(llm), "now": None}},
        )
