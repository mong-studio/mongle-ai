from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig


_OUT_OF_SCOPE_MESSAGE = (
    "나는 목표를 TODO랑 일정으로 차근차근 나눠주는 이장님이야. "
    "준비할 일이나 이루고 싶은 목표를 말해주면 같이 계획을 짜볼게."
)


async def out_of_scope_node(
    state: dict[str, Any], config: RunnableConfig
) -> dict[str, Any]:
    """플랜과 관련 없는 입력에는 고정 안내문만 반환한다."""

    return {
        "out_of_scope_message": _OUT_OF_SCOPE_MESSAGE,
        "todos": [],
        "calendar_events": [],
    }
