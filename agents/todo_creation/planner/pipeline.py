from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from agents.todo_creation.planner.graph import build_planner_graph
from agents.todo_creation.protocols import LLMPort
from agents.todo_creation.schemas import (
    FollowUpResult,
    CandidatesResult,
    PlannerInput,
    OutOfScopeResult,
    PlannerResult,
)


_ACCEPT_MESSAGES = {
    "좋아",
    "좋아요",
    "응",
    "네",
    "예",
    "그렇게 할게",
    "그렇게 할게요",
    "이대로 할게",
    "이대로 할게요",
    "확정",
    "확정할게",
    "확정할게요",
}


@dataclass
class PlannerPorts:
    llm: LLMPort
    classifier: LLMPort | None = None
    validator: LLMPort | None = None


_GRAPH = build_planner_graph()


async def run(
    input: PlannerInput,
    *,
    ports: PlannerPorts,
    now: datetime,
) -> PlannerResult:
    thread_id = input.thread_id or str(uuid4())
    config = {"configurable": {"ports": ports, "thread_id": thread_id}}

    graph_input: Any
    if input.thread_id is not None:
        snapshot = _GRAPH.get_state(config)
        if snapshot.next:
            # graph paused at follow_up interrupt — resume with user's answer
            graph_input = Command(resume=input.message)
        elif snapshot.values.get("plan"):
            if _is_acceptance(input.message):
                return _result_from_snapshot(thread_id, snapshot.values)
            graph_input = _revision_state(input, now, snapshot.values)
        else:
            graph_input = _initial_state(input, now)
    else:
        graph_input = _initial_state(input, now)

    interrupt_question: str | None = None
    final: dict[str, Any] = {}

    async for mode, chunk in _GRAPH.astream(
        graph_input, config=config, stream_mode=["updates", "values"]
    ):
        if mode == "updates" and "__interrupt__" in chunk:
            interrupts = chunk["__interrupt__"]
            interrupt_question = interrupts[0].value if interrupts else ""
        elif mode == "values":
            final = chunk

    if interrupt_question is not None:
        state_after = _GRAPH.get_state(config)
        return FollowUpResult(
            thread_id=thread_id,
            question=interrupt_question,
            missing_aspects=state_after.values.get("missing_aspects") or [],
        )

    if final.get("out_of_scope_message"):
        return OutOfScopeResult(
            thread_id=thread_id,
            message=final.get("out_of_scope_message") or "",
        )

    return CandidatesResult(
        thread_id=thread_id,
        todos=final.get("todos") or [],
        calendar_events=final.get("calendar_events") or [],
        summary_text=final.get("summary_text"),
        personalization_patch=final.get("personalization_patch"),
    )


def _is_acceptance(message: str) -> bool:
    """사용자가 직전 후보를 그대로 수락하면 LLM 재생성을 생략한다."""

    normalized = message.strip().replace(".", "").replace("!", "").replace("~", "")
    return normalized in _ACCEPT_MESSAGES


def _result_from_snapshot(thread_id: str, values: dict[str, Any]) -> CandidatesResult:
    """MemorySaver 에 남아 있는 직전 후보를 다시 반환한다."""

    return CandidatesResult(
        thread_id=thread_id,
        todos=values.get("todos") or [],
        calendar_events=values.get("calendar_events") or [],
        summary_text=values.get("summary_text"),
        personalization_patch=values.get("personalization_patch"),
    )


def _initial_state(input: PlannerInput, now: datetime) -> dict[str, Any]:
    return {
        "message": input.message,
        "today": input.today,
        "now": now,
        "user_id": input.user_id,
        "history": [],
        "recent_turns": [],
        "follow_up_count": 0,
        "user_profile_memory": input.user_profile_memory or {},
    }


def _revision_state(
    input: PlannerInput, now: datetime, previous: dict[str, Any]
) -> dict[str, Any]:
    return {
        **previous,
        "message": input.message,
        "today": input.today,
        "now": now,
        "user_id": input.user_id,
        "history": list(previous.get("history") or []),
        "recent_turns": list(previous.get("recent_turns") or []),
        "revision_request": input.message,
        "user_profile_memory": input.user_profile_memory
        or previous.get("user_profile_memory")
        or {},
    }


def get_debug_state(*, thread_id: str, ports: PlannerPorts) -> dict[str, Any]:
    """콘솔/테스트에서 현재 MemorySaver 상태를 확인하기 위한 읽기 전용 헬퍼."""

    config = {"configurable": {"ports": ports, "thread_id": thread_id}}
    snapshot = _GRAPH.get_state(config)
    values = snapshot.values or {}
    parsed_goal = values.get("parsed_goal") or {}
    return {
        "thread_id": thread_id,
        "storage_backend": type(_GRAPH.checkpointer).__name__,
        "next": tuple(snapshot.next or ()),
        "history_turns": len(values.get("history") or []),
        "recent_turns": values.get("recent_turns") or [],
        "user_profile_memory": values.get("user_profile_memory") or {},
        "personalization_patch": values.get("personalization_patch") or {},
        "parsed_goal": parsed_goal,
        "missing_aspects": values.get("missing_aspects") or [],
        "has_previous_plan": bool(values.get("plan")),
        "todo_count": len(values.get("todos") or []),
        "calendar_count": len(values.get("calendar_events") or []),
        "follow_up_count": int(values.get("follow_up_count") or 0),
    }
