from __future__ import annotations

from datetime import date

import pytest

from adapters.todo_creation.fake_llm import FakeLLM
from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.schemas import TaskCandidate


async def test_fake_llm_returns_scripted_response() -> None:
    tasks = [TaskCandidate(title="코테", due_date=date(2026, 5, 24))]
    llm = FakeLLM(responses=[tasks])
    out = await llm.split_tasks(prompt="오늘 코테", today=date(2026, 5, 24))
    assert out == tasks
    assert llm.calls == 1


async def test_fake_llm_fails_n_times_then_succeeds() -> None:
    tasks = [TaskCandidate(title="할 일", due_date=date(2026, 5, 24))]
    llm = FakeLLM(responses=[tasks], fail_times=2)
    with pytest.raises(LLMFailedError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))
    with pytest.raises(LLMFailedError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))
    out = await llm.split_tasks(prompt="x", today=date(2026, 5, 24))
    assert out == tasks
    assert llm.calls == 3


async def test_fake_llm_consumes_responses_queue() -> None:
    a = [TaskCandidate(title="A", due_date=date(2026, 5, 24))]
    b = [TaskCandidate(title="B", due_date=date(2026, 5, 24))]
    llm = FakeLLM(responses=[a, b])
    out1 = await llm.split_tasks(prompt="1", today=date(2026, 5, 24))
    out2 = await llm.split_tasks(prompt="2", today=date(2026, 5, 24))
    assert out1 == a
    assert out2 == b


async def test_fake_llm_exhausted_queue_raises() -> None:
    llm = FakeLLM(responses=[])
    with pytest.raises(IndexError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))
