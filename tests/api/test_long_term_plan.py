from __future__ import annotations

import asyncio
from datetime import date

import httpx

from agents.todo_creation.planner.pipeline import PlannerPorts
from agents.todo_creation.schemas import TaskCandidate
from api.deps import get_todo_planner_ports
from api.main import create_app
from api.todo_creation.jobs import TodoJobStore
from tests.api.conftest import AUTH, make_config


class _FakePlanLLM:
    """한 번에 충분 판정 후 2일짜리 plan 을 내놓는 planner LoRA 대역."""

    async def judge_sufficiency(self, *, history, message, today, user_profile_memory=None):
        goal = {"intent": "plan", "goal_text": "토익 800점", "goal_tag": "토익", "deadline": date(2026, 9, 19)}
        return True, [], goal

    async def generate_follow_up_question(self, *, missing_aspects, history):
        return "언제까지?"

    async def generate_plan(self, *, parsed_goal, today):
        plan = [
            {"date": today, "tasks": [TaskCandidate(title="기출 1세트", due_date=today)]},
            {"date": date(2026, 6, 20), "tasks": [TaskCandidate(title="LC 복습", due_date=date(2026, 6, 20))]},
        ]
        return "토익 800 3개월 계획", plan

    async def generate_goal_tag(self, *, parsed_goal, history):
        return parsed_goal.get("goal_tag", "목표")

    async def tag_plan(self, *, plan, parsed_goal):
        return plan


def _override():
    return PlannerPorts(llm=_FakePlanLLM())


def _make_app():
    app = create_app()
    app.state.config = make_config()
    app.state.todo_jobs = TodoJobStore()
    app.dependency_overrides[get_todo_planner_ports] = _override
    return app


def test_plan_submit_returns_pending_job_id(api_client):
    """POST /v1/plan/generate 는 202 + 폴링용 job_id 를 pending 봉투로 반환한다."""
    api_client.app.dependency_overrides[get_todo_planner_ports] = _override
    body = {"user_id": "u1", "goal": "3개월 안에 토익 800점", "today": "2026-06-19"}
    resp = api_client.post("/v1/plan/generate", json=body, headers=AUTH)
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"
    assert resp.json()["result"]["job_id"]


def test_plan_requires_api_key(api_client):
    assert api_client.post("/v1/plan/generate", json={"goal": "x"}).status_code == 401


def test_plan_poll_unknown_job_returns_404(api_client):
    assert api_client.get("/v1/plan/generate/nope", headers=AUTH).status_code == 404


async def test_plan_poll_returns_candidates_with_plan():
    """완료 시 일자별 plan 과 goal_tag 가 응답에 포함된다(기존엔 버려지던 값)."""
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = {"user_id": "u1", "goal": "3개월 안에 토익 800점", "today": "2026-06-19"}
        resp = await client.post("/v1/plan/generate", json=body, headers=AUTH)
        job_id = resp.json()["result"]["job_id"]

        data = {"status": "pending"}
        for _ in range(100):
            await asyncio.sleep(0)
            data = (await client.get(f"/v1/plan/generate/{job_id}", headers=AUTH)).json()
            if data["status"] != "pending":
                break

    assert data["status"] == "done"
    result = data["result"]
    assert result["kind"] == "candidates"
    assert result["goal_tag"] == "토익"
    assert len(result["plan"]) == 2
    assert result["plan"][0]["date"] == "2026-06-19"
    assert result["todos"][0]["title"] == "기출 1세트"
