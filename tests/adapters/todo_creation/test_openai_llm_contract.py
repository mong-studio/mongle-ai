from __future__ import annotations

import os
from datetime import date

import pytest

pytestmark = pytest.mark.contract


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set; contract test skipped",
)
async def test_real_openai_splits_prompt_into_today_and_future() -> None:
    from adapters.todo_creation.openai_llm import OpenAILLM

    llm = OpenAILLM(model="gpt-4o-mini")
    today = date(2026, 5, 24)
    out = await llm.split_tasks(prompt="오늘 코테 1개, 3일 뒤 발표", today=today)
    assert 1 <= len(out) <= 5
    today_tasks = [t for t in out if t.due_date == today]
    future_tasks = [t for t in out if t.due_date > today]
    assert today_tasks, f"expected at least one today task, got {out}"
    assert future_tasks, f"expected at least one future task, got {out}"


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set; contract test skipped",
)
async def test_real_openai_normalizes_colloquial_verb_and_movement() -> None:
    """구어체 동사 '내고' → '제출', 이동동사 '다녀올거야' → '가기' 정규화 검증."""
    from adapters.todo_creation.openai_llm import OpenAILLM

    llm = OpenAILLM(model="gpt-4o-mini")
    today = date(2026, 5, 27)
    out = await llm.split_tasks(
        prompt="오늘 전처리 결과서 내고, 운동 다녀올거야", today=today
    )

    titles = [t.title for t in out]
    assert len(out) == 2, f"expected 2 tasks, got {titles}"
    assert "전처리 결과서 제출" in titles, f"expected '전처리 결과서 제출' in {titles}"
    assert "운동가기" in titles, f"expected '운동가기' in {titles}"
