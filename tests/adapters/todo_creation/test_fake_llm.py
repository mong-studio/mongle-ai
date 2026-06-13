from __future__ import annotations

from datetime import date

import pytest

from tests.agents.todo_creation.fake_llm import FakeLLM
from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.schemas import SplitResult, TaskCandidate


# 검증 대상 기능: scripted fake 는 네트워크 없이 agent pipeline 을 구동한다.
async def test_fake_llm_returns_scripted_response() -> None:
    tasks = [TaskCandidate(title="코테", due_date=date(2026, 5, 24))]
    llm = FakeLLM(responses=[tasks])
    out = await llm.split_tasks(prompt="오늘 코테", today=date(2026, 5, 24))
    assert out.tasks == tasks
    assert llm.calls == 1


# 실패 시뮬레이션: 지정한 횟수만큼 LLMFailedError 를 낸 뒤 성공한다.
async def test_fake_llm_fails_n_times_then_succeeds() -> None:
    tasks = [TaskCandidate(title="할 일", due_date=date(2026, 5, 24))]
    llm = FakeLLM(responses=[tasks], fail_times=2)
    with pytest.raises(LLMFailedError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))
    with pytest.raises(LLMFailedError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))
    out = await llm.split_tasks(prompt="x", today=date(2026, 5, 24))
    assert out.tasks == tasks
    assert llm.calls == 3


# 응답 큐: 여러 호출에서 준비된 응답을 순서대로 소비한다.
async def test_fake_llm_consumes_responses_queue() -> None:
    a = [TaskCandidate(title="A", due_date=date(2026, 5, 24))]
    b = [TaskCandidate(title="B", due_date=date(2026, 5, 24))]
    llm = FakeLLM(responses=[a, b])
    out1 = await llm.split_tasks(prompt="1", today=date(2026, 5, 24))
    out2 = await llm.split_tasks(prompt="2", today=date(2026, 5, 24))
    assert out1.tasks == a
    assert out2.tasks == b


# 테스트 안전장치: 준비된 응답이 없으면 즉시 실패해 잘못된 호출을 드러낸다.
async def test_fake_llm_exhausted_queue_raises() -> None:
    llm = FakeLLM(responses=[])
    with pytest.raises(IndexError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))


# intent 큐: out_of_scope intent 가 SplitResult.intent 에 반영된다.
async def test_fake_llm_out_of_scope_intent() -> None:
    llm = FakeLLM(responses=[[]], intents=["out_of_scope"])
    out = await llm.split_tasks(prompt="배고프다", today=date(2026, 5, 24))
    assert isinstance(out, SplitResult)
    assert out.intent == "out_of_scope"
    assert out.tasks == []
