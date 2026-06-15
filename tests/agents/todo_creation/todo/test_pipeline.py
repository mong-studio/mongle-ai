from __future__ import annotations

from datetime import date, datetime

import pytest

from tests.agents.todo_creation.fake_llm import FakeLLM
from agents.todo_creation.exceptions import LLMFailedError, ValidationError
from agents.todo_creation.schemas import TodoInput, TaskCandidate
from agents.todo_creation.todo.pipeline import GeneratePorts, run


def _input(prompt: str = "오늘 코테") -> TodoInput:
    return TodoInput(user_id="u1", prompt=prompt, today=date(2026, 5, 24))


async def test_pipeline_run_returns_candidates_result() -> None:
    llm = FakeLLM(
        responses=[[TaskCandidate(title="코테", due_date=date(2026, 5, 24))]]
    )
    result = await run(
        _input(),
        ports=GeneratePorts(llm=llm),
        now=datetime(2026, 5, 24, 12, 0),
    )
    assert len(result.todos) == 1
    assert result.todos[0].title == "코테"


async def test_pipeline_run_raises_validation_error() -> None:
    bad = TodoInput.model_construct(
        user_id="u1", prompt="", today=date(2026, 5, 24)
    )
    with pytest.raises(ValidationError):
        await run(
            bad,
            ports=GeneratePorts(llm=FakeLLM()),
            now=datetime(2026, 5, 24, 12, 0),
        )


async def test_pipeline_run_raises_llm_failed_after_retries() -> None:
    llm = FakeLLM(fail_times=99, responses=[])
    with pytest.raises(LLMFailedError):
        await run(
            _input(),
            ports=GeneratePorts(llm=llm),
            now=datetime(2026, 5, 24, 12, 0),
        )


async def test_pipeline_returns_out_of_scope_result() -> None:
    from datetime import date, datetime
    from agents.todo_creation.schemas import OutOfScopeResult, TodoInput
    from agents.todo_creation.todo import pipeline as single_pipeline
    from agents.todo_creation.todo.pipeline import GeneratePorts
    from tests.agents.todo_creation.fake_llm import FakeLLM

    ports = GeneratePorts(llm=FakeLLM(responses=[[]], intents=["out_of_scope"]))
    result = await single_pipeline.run(
        TodoInput(user_id="u1", prompt="배고프다", today=date(2026, 6, 13)),
        ports=ports,
        now=datetime(2026, 6, 13, 9, 0),
    )
    assert isinstance(result, OutOfScopeResult)
    assert result.thread_id == ""
    assert result.message
