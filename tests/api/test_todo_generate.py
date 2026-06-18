from __future__ import annotations

import asyncio
from typing import cast

import httpx

from agents.todo_creation.protocols import LLMPort
from agents.todo_creation.schemas import SplitResult, TaskCandidate
from agents.todo_creation.todo.pipeline import GeneratePorts
from api.deps import get_todo_generate_ports
from api.main import create_app
from api.todo_creation.jobs import TodoJobStore
from tests.api.conftest import AUTH, make_config


class _FakeGenerateLLM:
    async def split_tasks(self, *, prompt, today):
        return SplitResult(
            intent="plan",
            tasks=[TaskCandidate(title="장보기", due_date=today, tags=[])],
        )


def _override():
    return GeneratePorts(llm=cast(LLMPort, _FakeGenerateLLM()))


class _FakeOutOfScopeLLM:
    async def split_tasks(self, *, prompt, today):
        return SplitResult(intent="out_of_scope", tasks=[])


def _override_oos():
    return GeneratePorts(llm=cast(LLMPort, _FakeOutOfScopeLLM()))


def _make_app(override):
    """단일 이벤트 루프 위에서 백그라운드 잡을 검증하기 위한 앱(테스트용 state 주입)."""
    app = create_app()
    app.state.config = make_config()
    app.state.todo_jobs = TodoJobStore()
    app.dependency_overrides[get_todo_generate_ports] = override
    return app


async def _submit_and_poll(override, body, *, attempts=100):
    app = _make_app(override)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/todo/generate", json=body, headers=AUTH)
        assert resp.status_code == 202
        assert resp.json()["status"] == "pending"
        job_id = resp.json()["result"]["job_id"]

        data = {"status": "pending"}
        for _ in range(attempts):
            await asyncio.sleep(0)
            poll = await client.get(f"/v1/todo/generate/{job_id}", headers=AUTH)
            data = poll.json()
            if data["status"] != "pending":
                break
        return data


# ---- submit(202) / 인증 / 검증 ----

def test_generate_submit_returns_pending_job_id(api_client):
    """POST /v1/todo/generate는 202와 함께 폴링용 job_id를 pending 봉투로 반환한다."""
    api_client.app.dependency_overrides[get_todo_generate_ports] = _override
    body = {"user_id": "u1", "prompt": "내일 장보기", "today": "2026-06-04"}
    resp = api_client.post("/v1/todo/generate", json=body, headers=AUTH)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert data["result"]["job_id"]


def test_generate_requires_api_key(api_client):
    """API 키 없이 /v1/todo/generate 호출 시 401을 반환한다."""
    body = {"user_id": "u1", "prompt": "x", "today": "2026-06-04"}
    assert api_client.post("/v1/todo/generate", json=body).status_code == 401


def test_generate_poll_requires_api_key(api_client):
    """API 키 없이 GET 폴링 호출 시 401을 반환한다."""
    assert api_client.get("/v1/todo/generate/whatever").status_code == 401


def test_generate_poll_unknown_job_returns_404(api_client):
    """존재하지 않는 job_id 폴링은 404를 반환한다."""
    resp = api_client.get("/v1/todo/generate/does-not-exist", headers=AUTH)
    assert resp.status_code == 404


def test_generate_validation_error_returns_422(api_client):
    """필수 필드가 빠지면 submit 단계에서 422 + "validation_error"를 반환한다."""
    api_client.app.dependency_overrides[get_todo_generate_ports] = _override
    resp = api_client.post("/v1/todo/generate", json={"user_id": "u1"}, headers=AUTH)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# ---- 비동기(백그라운드 완료) 케이스 ----

async def test_generate_poll_returns_candidates():
    """plan 입력 → 완료 시 후보 todo 목록을 done 봉투로 반환한다."""
    data = await _submit_and_poll(
        _override, {"user_id": "u1", "prompt": "내일 장보기", "today": "2026-06-04"}
    )
    assert data["status"] == "done"
    assert data["result"]["kind"] == "candidates"
    assert data["result"]["todos"][0]["title"] == "장보기"


async def test_generate_poll_returns_out_of_scope():
    """플랜과 무관한 입력은 완료 시 out_of_scope 봉투로 반환한다."""
    data = await _submit_and_poll(
        _override_oos, {"user_id": "u1", "prompt": "배고프다", "today": "2026-06-13"}
    )
    assert data["status"] == "done"
    assert data["result"]["kind"] == "out_of_scope"
    assert data["result"]["message"]
