from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.single_turn.pipeline import GeneratePorts
from api.deps import get_todo_generate_ports
from tests.api.conftest import AUTH


class _FakeGenerateLLM:
    async def split_tasks(self, *, prompt, today):
        return [TaskCandidate(title="장보기", due_date=today, tags=[])]


def _override():
    return GeneratePorts(llm=_FakeGenerateLLM())


def test_generate_returns_done_envelope(api_client):
    """/v1/todo/generate는 후보 todo 목록을 done 봉투로 반환한다."""
    api_client.app.dependency_overrides[get_todo_generate_ports] = _override
    body = {"user_id": "u1", "prompt": "내일 장보기", "today": "2026-06-04"}
    resp = api_client.post("/v1/todo/generate", json=body, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["result"]["kind"] == "candidates"
    assert data["result"]["todos"][0]["title"] == "장보기"


def test_generate_requires_api_key(api_client):
    """API 키 없이 /v1/todo/generate 호출 시 401을 반환한다."""
    body = {"user_id": "u1", "prompt": "x", "today": "2026-06-04"}
    assert api_client.post("/v1/todo/generate", json=body).status_code == 401


def test_generate_validation_error_returns_422(api_client):
    """필수 필드가 빠지면 422 + "validation_error"를 반환한다."""
    api_client.app.dependency_overrides[get_todo_generate_ports] = _override
    resp = api_client.post("/v1/todo/generate", json={"user_id": "u1"}, headers=AUTH)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
