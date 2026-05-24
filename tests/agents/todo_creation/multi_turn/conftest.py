from __future__ import annotations

from datetime import date, datetime

import pytest

from adapters.todo_creation.fake_multi_turn_llm import FakeMultiTurnLLM
from agents.todo_creation.multi_turn.session_store import InMemorySessionStore
from agents.todo_creation.schemas import MultiTurnInput


@pytest.fixture
def today() -> date:
    return date(2026, 5, 25)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 25, 12, 0, 0)


@pytest.fixture
def fake_mt_llm() -> FakeMultiTurnLLM:
    return FakeMultiTurnLLM()


@pytest.fixture
def session_store() -> InMemorySessionStore:
    return InMemorySessionStore()


@pytest.fixture
def base_input(today) -> MultiTurnInput:
    return MultiTurnInput(user_id="u1", session_id="s1", message="3일 후 정보처리기사 시험", today=today)
