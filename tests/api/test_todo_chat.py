from __future__ import annotations

from agents.todo_creation.multi_turn.pipeline import MultiTurnPorts
from api.deps import get_todo_multiturn_ports
from tests.api.conftest import AUTH


class _FakeMultiLLM:
    async def judge_sufficiency(self, *, history, message, today, user_profile_memory=None):
        from agents.todo_creation.state import ParsedGoal

        parsed_goal: ParsedGoal = {"goal_text": message, "deadline": None, "daily_capacity_minutes": None}
        return False, ["기간"], parsed_goal

    async def generate_follow_up_question(self, *, missing_aspects, history):
        return "언제까지 끝내고 싶으세요?"

    async def generate_plan(self, *, parsed_goal, today):
        return "", []

    async def tag_plan(self, *, plan, parsed_goal):
        return plan


def _override():
    return MultiTurnPorts(llm=_FakeMultiLLM())


def test_chat_first_turn_returns_follow_up(api_client):
    """첫 턴에서 정보가 부족하면 follow_up 질문과 thread_id를 반환한다."""
    api_client.app.dependency_overrides[get_todo_multiturn_ports] = _override
    body = {"mode": "multi", "user_id": "u1", "message": "운동 계획", "today": "2026-06-04"}
    resp = api_client.post("/v1/todo/chat", json=body, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["result"]["kind"] == "follow_up"
    assert data["result"]["thread_id"]
    assert data["result"]["question"]


def test_chat_requires_api_key(api_client):
    """API 키 없이 /v1/todo/chat 호출 시 401을 반환한다."""
    assert api_client.post("/v1/todo/chat", json={"mode": "multi"}).status_code == 401
