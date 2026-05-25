"""multi 모드 planner 노드.

LLMPort.judge_sufficiency 결과로 `Command(goto='plan_generator' | 'follow_up')`
분기. parsed_goal/sufficiency/missing_aspects 를 state 업데이트.

재시도 정책은 graph 등록 시점(`add_node(..., retry=RetryPolicy(3, LLMFailedError))`).
JSON 파싱 실패 등 LLMOutputError 는 그대로 raise.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command


async def planner_node(state: dict[str, Any], config: dict[str, Any]) -> Command:
    llm = config["configurable"]["ports"].llm
    sufficient, missing, parsed = await llm.judge_sufficiency(
        history=state.get("history", []),
        message=state.get("message", ""),
        today=state.get("today"),
    )
    return Command(
        goto="plan_generator" if sufficient else "follow_up",
        update={
            "sufficiency": bool(sufficient),
            "missing_aspects": list(missing or []),
            "parsed_goal": dict(parsed) if parsed else None,
        },
    )
