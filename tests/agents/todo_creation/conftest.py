from __future__ import annotations

from datetime import date, datetime

import pytest

from adapters.todo_creation.fake_llm import FakeLLM
from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from adapters.todo_creation.memory_repo import MemoryTodoRepository


@pytest.fixture
def today() -> date:
    return date(2026, 5, 24)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_repo() -> MemoryTodoRepository:
    return MemoryTodoRepository()


@pytest.fixture
def fake_counter() -> MemoryQuestCounter:
    return MemoryQuestCounter()
