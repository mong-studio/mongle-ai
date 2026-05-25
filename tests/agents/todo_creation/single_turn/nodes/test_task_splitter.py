from __future__ import annotations

from datetime import date

import pytest

from adapters.todo_creation.fake_llm import FakeLLM
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import SingleTurnInput, TaskCandidate
from agents.todo_creation.single_turn.nodes.task_splitter import task_splitter_node


def _input(prompt: str = "오늘 코테") -> SingleTurnInput:
    return SingleTurnInput(user_id="u1", prompt=prompt, today=date(2026, 5, 24))


def _t(title: str = "코테", d: date = date(2026, 5, 24)) -> TaskCandidate:
    return TaskCandidate(title=title, due_date=d)


def _state_and_config(llm: FakeLLM) -> tuple[dict, dict]:
    state = {"input": _input(), "now": None}

    class _P:
        pass

    p = _P()
    p.llm = llm
    config = {"configurable": {"ports": p, "now": None}}
    return state, config


async def test_returns_split_tasks_on_happy_path() -> None:
    llm = FakeLLM(responses=[[_t("코테"), _t("발표", date(2026, 5, 27))]])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert len(diff["split_tasks"]) == 2
    assert diff["split_tasks"][0].title == "코테"


async def test_propagates_llm_failure() -> None:
    llm = FakeLLM(fail_times=1, responses=[[_t()]])
    state, config = _state_and_config(llm)
    with pytest.raises(LLMFailedError):
        await task_splitter_node(state, config)


async def test_empty_response_retries_once() -> None:
    llm = FakeLLM(responses=[[], [_t("재시도 결과")]])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert len(diff["split_tasks"]) == 1
    assert llm.calls == 2


async def test_empty_twice_raises_llm_output_error() -> None:
    llm = FakeLLM(responses=[[], []])
    state, config = _state_and_config(llm)
    with pytest.raises(LLMOutputError):
        await task_splitter_node(state, config)


async def test_over_20_tasks_raises_llm_output_error() -> None:
    too_many = [_t(f"t{i}") for i in range(21)]
    llm = FakeLLM(responses=[too_many])
    state, config = _state_and_config(llm)
    with pytest.raises(LLMOutputError):
        await task_splitter_node(state, config)


async def test_past_date_corrected_to_today() -> None:
    yesterday = date(2026, 5, 23)
    llm = FakeLLM(responses=[[_t("어제 일", yesterday)]])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff["split_tasks"][0].due_date == date(2026, 5, 24)


async def test_future_date_preserved() -> None:
    future = date(2026, 5, 27)
    llm = FakeLLM(responses=[[_t("발표", future)]])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff["split_tasks"][0].due_date == future
