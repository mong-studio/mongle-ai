"""multi 모드 follow_up 노드 — interrupt 기반 resume.

planner 가 sufficiency=False 로 분기시킨 경우 진입. LLM 으로 한국어 꼬리 질문을
생성하고 `interrupt(question)` 으로 그래프 일시정지. resume 시 같은 노드가
user_answer 와 함께 재진입하며 history 에 assistant question + user answer 두
줄을 append 후 planner 로 add_edge.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.planner.conversation_style import render_chief_voice
from agents.todo_creation.planner.slot_schemas import slot_hints

_DATE_KEYS = {"deadline", "exam_date", "event_date", "horizon"}
_MAX_QUESTION_ASPECTS = 2


def _select_missing_aspects(missing: list[str], *, follow_up_count: int) -> list[str]:
    """한 번에 답하기 쉬운 핵심 조건만 고른다."""

    if follow_up_count > 0:
        return missing[:_MAX_QUESTION_ASPECTS]

    date_keys = [key for key in missing if key in _DATE_KEYS]
    if not date_keys:
        return missing[:_MAX_QUESTION_ASPECTS]

    selected = date_keys[:1]
    selected.extend(
        key
        for key in missing
        if key not in _DATE_KEYS and key not in selected
    )
    return selected[:_MAX_QUESTION_ASPECTS]


async def follow_up_node(
    state: dict[str, Any], config: RunnableConfig
) -> dict[str, Any]:
    ports = get_ports(config)
    question_llm = getattr(ports, "classifier", None) or ports.llm
    parsed_goal = state.get("parsed_goal") or {}
    follow_up_count = int(state.get("follow_up_count") or 0)
    missing = list(state.get("missing_aspects", []))
    selected = _select_missing_aspects(missing, follow_up_count=follow_up_count)
    question = await question_llm.generate_follow_up_question(
        missing_aspects=slot_hints(parsed_goal.get("plan_kind"), selected),
        history=state.get("history", []),
    )
    question = render_chief_voice(question, question=True)
    user_answer = interrupt(question)
    history = state.get("history", [])
    appended = [
        {"role": "assistant", "content": question},
        {"role": "user", "content": user_answer},
    ]
    return {
        "follow_up_question": question,
        "history": history + appended,
        "recent_turns": (state.get("recent_turns", []) + appended)[-6:],
        "follow_up_count": follow_up_count + 1,
    }
