from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.planner.nodes.out_of_scope import out_of_scope_node


def _config(llm: AsyncMock) -> dict:
    return {"configurable": {"ports": type("P", (), {"llm": llm})()}}


@pytest.mark.asyncio
async def test_uses_llm_reply_when_available() -> None:
    llm = AsyncMock()
    llm.generate_out_of_scope_reply = AsyncMock(
        return_value="그럴 수 있죠. 챙길 일이 생기면 일정으로 같이 정리해볼게요."
    )

    out = await out_of_scope_node(
        {
            "message": "아 배고파",
            "history": [{"role": "user", "content": "아 배고파"}],
        },
        _config(llm),
    )

    assert out["out_of_scope_message"].startswith("그럴 수 있죠")
    assert out["todos"] == []
    assert out["calendar_events"] == []
    llm.generate_out_of_scope_reply.assert_awaited_once_with(
        message="아 배고파",
        history=[{"role": "user", "content": "아 배고파"}],
    )


@pytest.mark.asyncio
async def test_falls_back_when_llm_reply_fails() -> None:
    llm = AsyncMock()
    llm.generate_out_of_scope_reply = AsyncMock(
        side_effect=LLMOutputError("bad reply")
    )

    out = await out_of_scope_node({"message": "아 배고파"}, _config(llm))

    assert "몸부터 챙기는" in out["out_of_scope_message"]


@pytest.mark.asyncio
async def test_falls_back_when_llm_claims_unsupported_search() -> None:
    """맛집 검색처럼 지원하지 않는 기능을 약속하면 안전 안내로 대체한다."""

    llm = AsyncMock()
    llm.generate_out_of_scope_reply = AsyncMock(
        return_value="마을 음식점에서 맛있는 걸 찾아드릴게요."
    )

    out = await out_of_scope_node({"message": "배고프다"}, _config(llm))

    assert "몸부터 챙기는" in out["out_of_scope_message"]
    assert "음식점" not in out["out_of_scope_message"]
