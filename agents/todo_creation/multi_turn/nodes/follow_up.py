"""multi 모드 follow_up 노드 — interrupt 기반 resume.

planner 가 sufficiency=False 로 분기시킨 경우 진입. LLM 으로 한국어 꼬리 질문을
생성하고 `interrupt(question)` 으로 그래프 일시정지. resume 시 같은 노드가
user_answer 와 함께 재진입하며 history 에 assistant question + user answer 두
줄을 append 후 planner 로 add_edge.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt


async def follow_up_node(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    question = await ports.llm.generate_follow_up_question(
        missing_aspects=state.get("missing_aspects", []),
        history=state.get("history", []),
    )
    user_answer = interrupt(question)
    history = state.get("history", [])
    return {
        "follow_up_question": question,
        "history": history
        + [
            {"role": "assistant", "content": question},
            {"role": "user", "content": user_answer},
        ],
    }
