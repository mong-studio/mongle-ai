from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import AppConfig
from api.main import create_app

API_KEY = "test-key"
AUTH = {"X-API-Key": API_KEY}


def make_config(**over) -> AppConfig:
    base: dict[str, Any] = dict(
        api_key=API_KEY,
        storage_backend="local",
        storage_prefix="mongle-village",
        local_storage_root=Path("/tmp/mongle-test"),
        aws_region=None,
        aws_s3_bucket=None,
        quest_llm_provider="fake",
        llm_provider="qwen",
        qwen_base_url="http://qwen-host/v1",
        qwen_model="planning-adapter",
        qwen_persona_model=None,
        qwen_api_key="EMPTY",
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
    app.state.image_generator = None
    return TestClient(app, raise_server_exceptions=False)
