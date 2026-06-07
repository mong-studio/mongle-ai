from uuid import uuid4

from agents.quest_generation.pipeline import Ports as QuestPorts
from api.deps import get_quest_ports
from tests.api.conftest import AUTH


class _FakeQuestLLM:
    async def generate_quest(self, *, character) -> str:
        return f"{character.name}의 모험"


def _override():
    return QuestPorts(llm=_FakeQuestLLM())


def test_quest_generate_returns_done(api_client):
    """/v1/quest/generate는 입력 todo별 퀘스트를 done 봉투로 반환한다."""
    api_client.app.dependency_overrides[get_quest_ports] = _override
    cid, tid = str(uuid4()), str(uuid4())
    body = {
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
    resp = api_client.post("/v1/quest/generate", json=body, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert len(data["result"]["generated"]) == 1
    assert data["result"]["generated"][0]["todo_id"] == tid


def test_quest_alias_accepts_server_spec_persona(api_client):
    """Django 명세 경로 /quest는 persona 단일 필드 입력도 agent 입력으로 변환한다."""
    api_client.app.dependency_overrides[get_quest_ports] = _override
    cid, tid = str(uuid4()), str(uuid4())
    body = {
        "todos": [{"todo_id": tid}],
        "characters": [
            {
                "character_id": cid,
                "name": "몽글이",
                "persona": "명랑하고 구름을 좋아함",
            }
        ],
        "remaining_daily_quota": 5,
    }
    resp = api_client.post("/quest", json=body, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["result"]["generated"][0]["character_id"] == cid


def test_quest_rejects_todo_content_to_keep_context_isolated(api_client):
    """퀘스트 생성 입력은 todo_id만 받아 TODO 내용을 구조적으로 격리한다."""
    api_client.app.dependency_overrides[get_quest_ports] = _override
    cid, tid = str(uuid4()), str(uuid4())
    body = {
        "todos": [{"todo_id": tid, "content": "운동하기"}],
        "characters": [
            {
                "character_id": cid,
                "name": "몽글이",
                "persona": "명랑",
            }
        ],
        "remaining_daily_quota": 5,
    }
    resp = api_client.post("/quest", json=body, headers=AUTH)
    assert resp.status_code == 422


def test_quest_requires_api_key(api_client):
    """API 키 없이 호출 시 401 + "unauthorized"를 반환한다."""
    resp = api_client.post("/v1/quest/generate", json={})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
