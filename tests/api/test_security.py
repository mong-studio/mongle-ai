from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.config import AppConfig
from api.security import require_api_key


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MONGLE_API_KEY", "secret-key")
    app = FastAPI()
    app.state.config = AppConfig(
        api_key="secret-key",
        storage_backend="local",
        storage_prefix="mongle-village",
        local_storage_root=Path("/tmp"),
        aws_region=None,
        aws_s3_bucket=None,
        quest_llm_provider="qwen",
        llm_provider="qwen",
        qwen_base_url="http://qwen-host/v1",
        qwen_model="Qwen/Qwen2.5-7B-Instruct",
        qwen_api_key="EMPTY",
        lora_dir="/tmp/lora",
    )

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


def test_quoted_key_is_normalized(client):
    """따옴표가 섞인 헤더 값도 동일 키로 정규화해 통과시킨다."""
    resp = client.get("/ping", headers={"X-API-Key": "'secret-key'"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_unconfigured_server_returns_500(monkeypatch):
    """app.state/config와 환경변수 모두 비어 있으면 500을 반환한다."""
    monkeypatch.delenv("MONGLE_API_KEY", raising=False)
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(require_api_key)])
    def ping():
        return {"ok": True}

    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/ping", headers={"X-API-Key": "anything"}).status_code == 500


def test_environment_fallback_still_works(monkeypatch):
    """앱 설정이 없으면 기존 환경변수 fallback으로도 인증 가능하다."""
    monkeypatch.setenv("MONGLE_API_KEY", "secret-key")
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(require_api_key)])
    def ping():
        return {"ok": True}

    c = TestClient(app, raise_server_exceptions=False)
    resp = c.get("/ping", headers={"X-API-Key": "secret-key"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
