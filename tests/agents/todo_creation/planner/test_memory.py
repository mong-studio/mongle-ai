from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from agents.todo_creation.planner import pipeline
from agents.todo_creation.planner.memory import fold_history


def _turns(n: int) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"t{i}"}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_fold_history_noop_below_trigger() -> None:
    llm = AsyncMock()
    history = _turns(3)  # trigger(3) 이하 → 그대로
    new_history, summary = await fold_history(history, None, llm=llm)
    assert new_history == history
    assert summary is None
    llm.summarize_history.assert_not_called()


@pytest.mark.asyncio
async def test_fold_history_summarizes_and_trims() -> None:
    llm = AsyncMock()
    llm.summarize_history = AsyncMock(return_value="목표=토익, 마감 미정")
    history = _turns(4)  # 2회 되묻기 = 4턴 > trigger

    new_history, summary = await fold_history(history, None, llm=llm)

    # 요약 1턴 + 최근 2턴(KEEP_RECENT)
    assert len(new_history) == 3
    assert new_history[0]["content"].startswith("[이전 대화 요약] ")
    assert "목표=토익" in new_history[0]["content"]
    assert new_history[1:] == history[-2:]
    assert summary == {"text": "목표=토익, 마감 미정"}


@pytest.mark.asyncio
async def test_fold_history_truncates_when_summary_unavailable() -> None:
    # summarize_history 미구현 LLM → 요약 없이 최근만 유지(여전히 bounded)
    llm = object()
    history = _turns(4)
    new_history, summary = await fold_history(history, {"text": "old"}, llm=llm)
    assert new_history == history[-2:]
    assert summary == {"text": "old"}  # 기존 요약 보존


@pytest.mark.asyncio
async def test_fold_history_falls_back_on_summary_error() -> None:
    llm = AsyncMock()
    llm.summarize_history = AsyncMock(side_effect=RuntimeError("boom"))
    history = _turns(4)
    new_history, summary = await fold_history(history, None, llm=llm)
    assert new_history == history[-2:]
    assert summary is None


def test_touch_thread_evicts_oldest_beyond_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "_MAX_LIVE_THREADS", 3)
    monkeypatch.setattr(pipeline, "_live_threads", pipeline.OrderedDict())
    spy = Mock()
    monkeypatch.setattr(pipeline._GRAPH.checkpointer, "delete_thread", spy)

    for tid in ["a", "b", "c", "d"]:
        pipeline._touch_thread(tid)

    assert list(pipeline._live_threads) == ["b", "c", "d"]  # a evicted
    spy.assert_called_once_with("a")


def test_touch_thread_refreshes_lru(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "_MAX_LIVE_THREADS", 2)
    monkeypatch.setattr(pipeline, "_live_threads", pipeline.OrderedDict())
    monkeypatch.setattr(pipeline._GRAPH.checkpointer, "delete_thread", Mock())

    pipeline._touch_thread("a")
    pipeline._touch_thread("b")
    pipeline._touch_thread("a")  # a 재방문 → 최신으로
    pipeline._touch_thread("c")  # b 가 가장 오래됨 → evict

    assert list(pipeline._live_threads) == ["a", "c"]
