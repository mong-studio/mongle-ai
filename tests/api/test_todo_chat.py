from __future__ import annotations

import asyncio

import httpx

from agents.todo_creation.planner.pipeline import PlannerPorts
from api.deps import get_todo_planner_ports
from api.main import create_app
from api.todo_creation.jobs import TodoJobStore
from tests.api.conftest import AUTH, make_config


class _FakeMultiLLM:
    async def judge_sufficiency(self, *, history, message, today):
        from agents.todo_creation.state import ParsedGoal

        parsed_goal: ParsedGoal = {
            "goal_text": message,
            "deadline": None,
            "daily_capacity_minutes": None,
        }
        return False, ["기간"], parsed_goal

    async def generate_follow_up_question(self, *, missing_aspects, history):
        return "언제까지 끝내고 싶으세요?"

    async def generate_plan(self, *, parsed_goal, today, temperature=None):
        return "", []

    async def tag_plan(self, *, plan, parsed_goal):
        return plan


def _override():
    return PlannerPorts(llm=_FakeMultiLLM())


def _make_app():
    """단일 이벤트 루프 위에서 백그라운드 잡을 검증하기 위한 앱(테스트용 state 주입)."""
    app = create_app()
    app.state.config = make_config()
    app.state.todo_jobs = TodoJobStore()
    app.dependency_overrides[get_todo_planner_ports] = _override
    return app


async def _submit_and_poll(body, *, attempts=100):
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/todo/chat", json=body, headers=AUTH)
        assert resp.status_code == 202
        assert resp.json()["status"] == "pending"
        job_id = resp.json()["result"]["job_id"]

        data = {"status": "pending"}
        for _ in range(attempts):
            await asyncio.sleep(0)
            poll = await client.get(f"/v1/todo/chat/{job_id}", headers=AUTH)
            data = poll.json()
            if data["status"] != "pending":
                break
        return data


# ---- submit(202) / 인증 ----

def test_chat_submit_returns_pending_job_id(api_client):
    """POST /v1/todo/chat는 202와 함께 폴링용 job_id를 pending 봉투로 반환한다."""
    api_client.app.dependency_overrides[get_todo_planner_ports] = _override
    body = {"mode": "multi", "user_id": "u1", "message": "운동 계획", "today": "2026-06-04"}
    resp = api_client.post("/v1/todo/chat", json=body, headers=AUTH)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert data["result"]["job_id"]


def test_chat_requires_api_key(api_client):
    """API 키 없이 /v1/todo/chat 호출 시 401을 반환한다."""
    assert api_client.post("/v1/todo/chat", json={"mode": "multi"}).status_code == 401


def test_chat_poll_requires_api_key(api_client):
    """API 키 없이 GET 폴링 호출 시 401을 반환한다."""
    assert api_client.get("/v1/todo/chat/whatever").status_code == 401


def test_chat_poll_unknown_job_returns_404(api_client):
    """존재하지 않는 job_id 폴링은 404를 반환한다."""
    resp = api_client.get("/v1/todo/chat/does-not-exist", headers=AUTH)
    assert resp.status_code == 404


# ---- 비동기(백그라운드 완료) 케이스 ----

async def test_chat_poll_returns_follow_up():
    """첫 턴에서 정보가 부족하면 완료 시 follow_up 질문과 thread_id를 반환한다."""
    data = await _submit_and_poll(
        {"mode": "multi", "user_id": "u1", "message": "운동 계획", "today": "2026-06-04"}
    )
    assert data["status"] == "done"
    assert data["result"]["kind"] == "follow_up"
    assert data["result"]["thread_id"]
    assert data["result"]["question"]
