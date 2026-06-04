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
    assert client.get("/ping").status_code == 401


def test_wrong_key_returns_401(client):
    assert client.get("/ping", headers={"X-API-Key": "nope"}).status_code == 401


def test_correct_key_passes(client):
    resp = client.get("/ping", headers={"X-API-Key": "secret-key"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_unconfigured_server_returns_500(monkeypatch):
    monkeypatch.delenv("MONGLE_API_KEY", raising=False)
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(require_api_key)])
    def ping():
        return {"ok": True}

    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/ping", headers={"X-API-Key": "anything"}).status_code == 500
