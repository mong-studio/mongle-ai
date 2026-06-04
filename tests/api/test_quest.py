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


def test_quest_requires_api_key(api_client):
    """API 키 없이 호출 시 401 + "unauthorized"를 반환한다."""
    resp = api_client.post("/v1/quest/generate", json={})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
