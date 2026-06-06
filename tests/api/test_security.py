import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.security import require_api_key


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MONGLE_API_KEY", "secret-key")
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(require_api_key)])
    def ping():
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_missing_key_returns_401(client):
    """X-API-Key 헤더가 없으면 401을 반환한다."""
    assert client.get("/ping").status_code == 401


def test_wrong_key_returns_401(client):
    """잘못된 X-API-Key면 401을 반환한다."""
    assert client.get("/ping", headers={"X-API-Key": "nope"}).status_code == 401


def test_correct_key_passes(client):
    """올바른 X-API-Key면 200으로 통과한다."""
    resp = client.get("/ping", headers={"X-API-Key": "secret-key"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_unconfigured_server_returns_500(monkeypatch):
    """서버에 MONGLE_API_KEY가 설정 안 됐으면 500을 반환한다."""
    monkeypatch.delenv("MONGLE_API_KEY", raising=False)
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(require_api_key)])
    def ping():
        return {"ok": True}

    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/ping", headers={"X-API-Key": "anything"}).status_code == 500
