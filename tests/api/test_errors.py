from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.quest_generation.exceptions import LLMFailedError
from agents.todo_creation.exceptions import SaveFailedError
from api.errors import install_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/llm")
    def _llm():
        raise LLMFailedError("llm down")

    @app.get("/img")
    def _img():
        raise ImageGenerationFailedError("no gpu")

    @app.get("/save")
    def _save():
        raise SaveFailedError("db down")

    @app.get("/boom")
    def _boom():
        raise RuntimeError("unexpected secret detail")

    return TestClient(app, raise_server_exceptions=False)


def test_llm_failure_maps_to_502_with_code():
    resp = _client().get("/llm")
    assert resp.status_code == 502
    body = resp.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "llm_failed"


def test_image_generation_failure_maps_to_502():
    resp = _client().get("/img")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "image_generation_failed"


def test_save_failure_maps_to_502():
    resp = _client().get("/save")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "storage_failed"


def test_unexpected_error_maps_to_500_without_leaking_message():
    resp = _client().get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert "secret detail" not in body["error"]["message"]


def test_validation_error_uses_envelope():
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI()
    install_error_handlers(app)

    class Body(BaseModel):
        n: int

    @app.post("/v")
    def _v(body: Body):
        return {"ok": True}

    c = TestClient(app, raise_server_exceptions=False)
    resp = c.post("/v", json={})  # missing required field n
    assert resp.status_code == 422
    body = resp.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "validation_error"


def test_http_exception_401_uses_envelope():
    from fastapi import Depends, FastAPI, HTTPException, status

    app = FastAPI()
    install_error_handlers(app)

    def _guard():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="nope")

    @app.get("/g", dependencies=[Depends(_guard)])
    def _g():
        return {"ok": True}

    c = TestClient(app, raise_server_exceptions=False)
    resp = c.get("/g")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
