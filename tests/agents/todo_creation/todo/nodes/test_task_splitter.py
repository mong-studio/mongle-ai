from __future__ import annotations

from datetime import date

import pytest

from tests.agents.todo_creation.fake_llm import FakeLLM
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import TodoInput, TaskCandidate
from agents.todo_creation.todo.nodes.task_splitter import task_splitter_node


def _input(prompt: str = "오늘 코테") -> TodoInput:
    return TodoInput(user_id="u1", message=prompt, today=date(2026, 5, 24))


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


async def test_node_passes_through_resolved_dates() -> None:
    # 날짜 계산/클램프는 split_tasks(resolver)가 끝낸다. 노드는 그대로 통과.
    future = date(2026, 5, 27)
    llm = FakeLLM(responses=[[_t("발표", future)]])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff["split_tasks"][0].due_date == future


async def test_out_of_scope_sets_intent_and_no_split() -> None:
    llm = FakeLLM(responses=[[]], intents=["out_of_scope"])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff["intent"] == "out_of_scope"
    assert "split_tasks" not in diff
    assert llm.calls == 1


async def test_plan_intent_sets_split_tasks() -> None:
    llm = FakeLLM(responses=[[_t("코테")]], intents=["plan"])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff["intent"] == "plan"
    assert len(diff["split_tasks"]) == 1
