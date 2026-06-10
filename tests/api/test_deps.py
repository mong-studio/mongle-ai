import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from api.config import AppConfig
from api.deps import (
    _get_image_generator,
    _s3_client,
    build_commit_ports,
    build_quest_ports,
    build_todo_generate_ports,
    build_todo_multiturn_ports,
    fetch_source_bytes,
    get_config,
)


def _cfg(**over) -> AppConfig:
    base: dict[str, Any] = dict(
        api_key="k",
        storage_backend="local",
        storage_prefix="p",
        local_storage_root=Path("/tmp"),
        aws_region=None,
        aws_s3_bucket=None,
        quest_llm_provider="fake",
        llm_provider="qwen",
        qwen_base_url=None,
        qwen_model=None,
        qwen_persona_model=None,
        qwen_api_key="EMPTY",
        lora_dir="/tmp/lora",
    )
    base.update(over)
    return AppConfig(**base)


def test_quest_ports_qwen_provider_builds():
    """qwen 프로바이더로 quest 포트가 빌드된다."""
    ports = build_quest_ports(_cfg())
    assert ports.llm is not None


def test_todo_generate_ports_qwen_builds():
    """todo 생성은 Qwen 전용 — qwen 설정으로 포트가 빌드된다."""
    ports = build_todo_generate_ports(
        _cfg(qwen_base_url="http://qwen-host/v1", qwen_model="planning-adapter")
    )
    assert ports.llm is not None


def test_todo_generate_ports_without_qwen_raises():
    """todo 는 Qwen 전용이라 qwen 설정이 없으면 RuntimeError 를 던진다."""
    with pytest.raises(RuntimeError, match="Qwen"):
        build_todo_generate_ports(_cfg(qwen_base_url=None, qwen_model=None))


# ---------------------------------------------------------------------------
# build_todo_multiturn_ports
# ---------------------------------------------------------------------------

def test_build_todo_multiturn_ports_qwen():
    """멀티턴 todo 도 Qwen 전용 — qwen 설정으로 빌드된다."""
    ports = build_todo_multiturn_ports(
        _cfg(qwen_base_url="http://qwen-host/v1", qwen_model="planning-adapter")
    )
    assert ports.llm is not None


# ---------------------------------------------------------------------------
# build_commit_ports
# ---------------------------------------------------------------------------

def test_build_commit_ports_returns_ports():
    """commit 포트에 repository·quest_counter·quest_dispatch가 모두 채워진다."""
    ports = build_commit_ports(_cfg(), remaining_daily_quota=3)
    assert ports.repository is not None
    assert ports.quest_counter is not None
    assert ports.quest_dispatch is not None


def test_build_commit_ports_quest_counter_remaining():
    """요청당 남은 할당량이 quest_counter.remaining에 그대로 반영된다."""
    ports = build_commit_ports(_cfg(), remaining_daily_quota=7)
    assert ports.quest_counter.remaining == 7


def test_build_commit_ports_zero_quota():
    """남은 할당량이 0이면 quest_counter.remaining도 0이다."""
    ports = build_commit_ports(_cfg(), remaining_daily_quota=0)
    assert ports.quest_counter.remaining == 0


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------

def test_get_config_returns_state_config():
    """get_config는 app.state에 보관된 config 객체를 그대로 반환한다."""
    cfg = _cfg()
    fake_request = types.SimpleNamespace(
        app=types.SimpleNamespace(
            state=types.SimpleNamespace(config=cfg)
        )
    )
    assert get_config(fake_request) is cfg


# ---------------------------------------------------------------------------
# fetch_source_bytes — local branch
# ---------------------------------------------------------------------------

async def test_fetch_source_bytes_local(tmp_path):
    """local 백엔드에서 키 경로의 파일 바이트를 읽어 온다."""
    content = b"hello image bytes"
    key = "uploads/test_image.png"
    file_path = tmp_path / key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)

    cfg = _cfg(local_storage_root=tmp_path)
    result = await fetch_source_bytes(cfg, key=key, content_type="image/png")
    assert result == content


async def test_fetch_source_bytes_local_nested_key(tmp_path):
    """중첩 경로 키도 local 백엔드에서 올바로 읽어 온다."""
    content = b"\x89PNG\r\n\x1a\n"
    key = "a/b/c/img.png"
    (tmp_path / "a" / "b" / "c").mkdir(parents=True, exist_ok=True)
    (tmp_path / key).write_bytes(content)

    cfg = _cfg(local_storage_root=tmp_path)
    result = await fetch_source_bytes(cfg, key=key, content_type="image/png")
    assert result == content


# ---------------------------------------------------------------------------
# qwen branch — build_quest_ports and build_todo_generate_ports
# (QwenLLM is a @dataclass; __init__ only stores fields, no network call)
# ---------------------------------------------------------------------------

def test_build_quest_ports_qwen_builds():
    """qwen 프로바이더로 quest 포트가 빌드된다(네트워크 호출 없음)."""
    ports = build_quest_ports(
        _cfg(
            quest_llm_provider="qwen",
            qwen_base_url="http://qwen-host/v1",
            qwen_model="Qwen/Qwen2.5-7B-Instruct",
            qwen_api_key="EMPTY",
        )
    )
    assert ports.llm is not None


def test_build_todo_generate_ports_qwen_builds():
    """qwen 프로바이더로 todo 생성 포트가 빌드된다."""
    ports = build_todo_generate_ports(
        _cfg(
            llm_provider="qwen",
            qwen_base_url="http://qwen-host/v1",
            qwen_model="Qwen/Qwen2.5-7B-Instruct",
            qwen_api_key="EMPTY",
        )
    )
    assert ports.llm is not None


def test_build_todo_multiturn_ports_qwen_builds():
    """qwen 프로바이더로 멀티턴 포트가 빌드된다."""
    ports = build_todo_multiturn_ports(
        _cfg(
            llm_provider="qwen",
            qwen_base_url="http://qwen-host/v1",
            qwen_model="Qwen/Qwen2.5-7B-Instruct",
            qwen_api_key="EMPTY",
        )
    )
    assert ports.llm is not None


def test_build_character_llm_uses_persona_model():
    """qwen 프로바이더에서 character LLM 은 persona 어댑터 모델명을 사용한다."""
    from api.deps import _build_character_llm

    llm = _build_character_llm(
        _cfg(
            llm_provider="qwen",
            qwen_base_url="http://qwen-host/v1",
            qwen_model="planning-adapter",
            qwen_persona_model="persona-adapter",
            qwen_api_key="EMPTY",
        )
    )
    assert llm.model == "persona-adapter"
    assert llm.base_url == "http://qwen-host/v1"


def test_build_todo_llm_uses_planning_model():
    """qwen 프로바이더에서 todo LLM 은 planning(기본) 어댑터 모델명을 사용한다."""
    from api.deps import _build_todo_llm

    llm = _build_todo_llm(
        _cfg(
            llm_provider="qwen",
            qwen_base_url="http://qwen-host/v1",
            qwen_model="planning-adapter",
            qwen_persona_model="persona-adapter",
            qwen_api_key="EMPTY",
        )
    )
    assert llm.model == "planning-adapter"


# ---------------------------------------------------------------------------
# _get_image_generator — provider 분기
# ---------------------------------------------------------------------------

def _fake_request(cfg: AppConfig) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        app=types.SimpleNamespace(
            state=types.SimpleNamespace(config=cfg, image_generator=None)
        )
    )


def test_image_generator_runpod_builds_and_caches():
    """runpod 프로바이더면 RunPodImageGenerator 를 만들고 재사용한다."""
    from adapters.character_creation.runpod_image import RunPodImageGenerator

    cfg = _cfg(
        image_provider="runpod",
        runpod_image_endpoint_url="https://api.runpod.ai/v2/ep-1",
        runpod_api_key="rp-key",
        lora_dir="",
    )
    request = _fake_request(cfg)

    gen = _get_image_generator(request)

    assert isinstance(gen, RunPodImageGenerator)
    assert _get_image_generator(request) is gen


# ---------------------------------------------------------------------------
# _s3_client — presigned URL 307→403 회귀 방지
#   endpoint_url 없이 client 를 만들면 presigned URL 이 글로벌 엔드포인트로 생성되어
#   GET 시 리전으로 307 리다이렉트되고 SigV4 서명이 깨져 403 이 난다.
# ---------------------------------------------------------------------------

def test_s3_client_pins_regional_endpoint(monkeypatch):
    """region 이 있으면 리전 엔드포인트를 명시해 boto3 client 를 만든다."""
    captured: dict[str, object] = {}

    def fake_client(service: str, **kwargs: object) -> MagicMock:
        captured["service"] = service
        captured["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr("boto3.client", fake_client)

    _s3_client(_cfg(storage_backend="s3", aws_region="ap-northeast-2"))

    assert captured["service"] == "s3"
    assert captured["kwargs"] == {
        "region_name": "ap-northeast-2",
        "endpoint_url": "https://s3.ap-northeast-2.amazonaws.com",
    }


def test_s3_client_no_region_leaves_endpoint_none(monkeypatch):
    """region 이 없으면 endpoint_url 을 None 으로 둔다(잘못된 URL 생성 방지)."""
    captured: dict[str, object] = {}

    def fake_client(service: str, **kwargs: object) -> MagicMock:
        captured["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr("boto3.client", fake_client)

    _s3_client(_cfg(storage_backend="s3", aws_region=None))

    assert captured["kwargs"] == {"region_name": None, "endpoint_url": None}
