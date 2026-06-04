from uuid import uuid4

from tests.api.conftest import AUTH


def _commit_body(remaining: int):
    return {
        "input": {
            "user_id": "u1",
            "idempotency_key": str(uuid4()),
            "today": "2026-06-04",
            "todos": [{"title": "오늘 할 일", "due_date": "2026-06-04", "tags": []}],
            "calendar_events": [],
        },
        "remaining_daily_quota": remaining,
    }


def test_commit_triggers_quest_when_quota_available(api_client):
    resp = api_client.post("/v1/todo/commit", json=_commit_body(5), headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["result"]["quest_distribution_triggered"] is True
    assert len(data["result"]["todo_ids"]) == 1


def test_commit_no_quest_when_quota_zero(api_client):
    resp = api_client.post("/v1/todo/commit", json=_commit_body(0), headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["result"]["quest_distribution_triggered"] is False


def test_commit_requires_api_key(api_client):
    assert api_client.post("/v1/todo/commit", json=_commit_body(5)).status_code == 401
