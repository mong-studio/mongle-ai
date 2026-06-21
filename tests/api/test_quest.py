from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx

from agents.quest_generation.pipeline import Ports as QuestPorts
from api.deps import get_quest_ports
from api.main import create_app
from api.todo_creation.jobs import TodoJobStore
from tests.api.conftest import AUTH, make_config


class _FakeQuestLLM:
    async def generate_quest(self, *, character) -> str:
        return f"{character.name}의 모험"


def _override():
    return QuestPorts(llm=_FakeQuestLLM())


def _make_app():
    """단일 이벤트 루프 위에서 백그라운드 잡을 검증하기 위한 앱(테스트용 state 주입)."""
    app = create_app()
    app.state.config = make_config()
    app.state.quest_jobs = TodoJobStore()
    app.dependency_overrides[get_quest_ports] = _override
    return app


async def _submit_and_poll(body, *, attempts=100):
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/quest/generate", json=body, headers=AUTH)
        assert resp.status_code == 202
        assert resp.json()["status"] == "pending"
        job_id = resp.json()["result"]["job_id"]

        data = {"status": "pending"}
        for _ in range(attempts):
            await asyncio.sleep(0)
            poll = await client.get(f"/v1/quest/generate/{job_id}", headers=AUTH)
            data = poll.json()
            if data["status"] != "pending":
                break
        return data


# ---- submit(202) / 인증 / 검증 ----

def test_quest_submit_returns_pending_job_id(api_client):
    """POST /v1/quest/generate는 202와 함께 폴링용 job_id를 pending 봉투로 반환한다."""
    api_client.app.dependency_overrides[get_quest_ports] = _override
    cid, tid = str(uuid4()), str(uuid4())
    body = {
        "todos": [{"todo_id": tid}],
        "characters": [{"character_id": cid, "name": "몽글이", "persona": "명랑"}],
        "remaining_daily_quota": 5,
    }
    resp = api_client.post("/v1/quest/generate", json=body, headers=AUTH)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert data["result"]["job_id"]


def test_quest_requires_api_key(api_client):
    """API 키 없이 호출 시 401 + "unauthorized"를 반환한다."""
    resp = api_client.post("/v1/quest/generate", json={})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_quest_poll_requires_api_key(api_client):
    """API 키 없이 GET 폴링 호출 시 401을 반환한다."""
    assert api_client.get("/v1/quest/generate/whatever").status_code == 401


def test_quest_poll_unknown_job_returns_404(api_client):
    """존재하지 않는 job_id 폴링은 404를 반환한다."""
    resp = api_client.get("/v1/quest/generate/does-not-exist", headers=AUTH)
    assert resp.status_code == 404


def test_quest_rejects_todo_content_to_keep_context_isolated(api_client):
    """퀘스트 생성 입력은 todo_id만 받아 TODO 내용을 구조적으로 격리한다(submit 단계 422)."""
    api_client.app.dependency_overrides[get_quest_ports] = _override
    cid, tid = str(uuid4()), str(uuid4())
    body = {
        "todos": [{"todo_id": tid, "content": "운동하기"}],
        "characters": [{"character_id": cid, "name": "몽글이", "persona": "명랑"}],
        "remaining_daily_quota": 5,
    }
    resp = api_client.post("/v1/quest/generate", json=body, headers=AUTH)
    assert resp.status_code == 422


# ---- 비동기(백그라운드 완료) 케이스 ----

async def test_quest_poll_returns_generated_quest():
    """입력 todo별 퀘스트를 완료 시 done 봉투로 반환한다."""
    cid, tid = str(uuid4()), str(uuid4())
    data = await _submit_and_poll(
        {
            "todos": [{"todo_id": tid}],
            "characters": [
                {
                    "character_id": cid,
                    "name": "몽글이",
                    "personality": "명랑",
                    "speech_style": "반말",
                    "appearance_keywords": [],
                }
            ],
            "remaining_daily_quota": 5,
        }
    )
    assert data["status"] == "done"
    assert len(data["result"]["generated"]) == 1
    assert data["result"]["generated"][0]["todo_id"] == tid


async def test_quest_poll_accepts_server_spec_persona():
    """Django가 보내는 persona 단일 필드 입력도 변환해 완료한다."""
    cid, tid = str(uuid4()), str(uuid4())
    data = await _submit_and_poll(
        {
            "todos": [{"todo_id": tid}],
            "characters": [
                {"character_id": cid, "name": "몽글이", "persona": "명랑하고 구름을 좋아함"}
            ],
            "remaining_daily_quota": 5,
        }
    )
    assert data["status"] == "done"
    assert data["result"]["generated"][0]["character_id"] == cid
