from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.schemas import ChatMessage, SessionState, TurnResult


async def present_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    now = config["configurable"]["now"]
    input_ = state["input"]

    # commit_invoke 가 이미 result + session.delete 완료한 분기
    if state.get("result") and state["result"].kind == "committed":
        return {"result": state["result"]}

    follow_up = state.get("follow_up_question")
    current_plan = state.get("current_plan")
    history = list(state.get("history") or [])

    if follow_up is not None:
        history.append(ChatMessage(role="assistant", content=follow_up))
        result = TurnResult(kind="question", question=follow_up)
        new_phase = "gathering"
    else:
        assert current_plan is not None
        history.append(ChatMessage(role="assistant", content=current_plan.summary_text))
        result = TurnResult(kind="plan", plan=current_plan)
        new_phase = "reviewing"

    session_state = SessionState(
        session_id=input_.session_id, user_id=input_.user_id, phase=new_phase,
        history=history[-20:],
        parsed_goal=state.get("parsed_goal"),
        current_plan=current_plan,
        created_at=now, updated_at=now,
    )
    await ports.session_store.save(state=session_state)
    return {"result": result}
