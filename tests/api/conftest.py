from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import AppConfig, QwenEndpoint
from api.main import create_app

API_KEY = "test-key"
AUTH = {"X-API-Key": API_KEY}


def _qwen() -> QwenEndpoint:
    return QwenEndpoint(
        base_url="http://localhost:8000/v1", model="Qwen/Qwen2.5-7B-Instruct", api_key="EMPTY"
    )


def make_config(**over) -> AppConfig:
    base = dict(
        api_key=API_KEY,
        openai_api_key="sk-test",
        storage_backend="local",
        storage_prefix="mongle-village",
        local_storage_root=Path("/tmp/mongle-test"),
        aws_region=None,
        aws_s3_bucket=None,
        qwen_todo=_qwen(),
        qwen_character=_qwen(),
        qwen_quest=_qwen(),
        lora_dir="/tmp/lora",
    )
    base.update(over)
    return AppConfig(**base)


@pytest.fixture
def api_client(monkeypatch):
    """config 를 주입한 TestClient. lifespan 의 from_env() 를 우회한다."""
    monkeypatch.setenv("MONGLE_API_KEY", API_KEY)
    app = create_app()
    app.state.config = make_config()
    app.state.lora_generator = None
    return TestClient(app, raise_server_exceptions=False)
