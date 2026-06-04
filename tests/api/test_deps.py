import types
from pathlib import Path

import pytest

from api.config import AppConfig
from api.deps import (
    build_commit_ports,
    build_quest_ports,
    build_todo_generate_ports,
    build_todo_multiturn_ports,
    fetch_source_bytes,
    get_config,
)


def _cfg(**over) -> AppConfig:
    base = dict(
        api_key="k",
        openai_api_key="sk",
        storage_backend="local",
        storage_prefix="p",
        local_storage_root=Path("/tmp"),
        aws_region=None,
        aws_s3_bucket=None,
        quest_llm_provider="fake",
        llm_provider="openai",
        midm_base_url=None,
        midm_model=None,
        midm_api_key="EMPTY",
        lora_dir="/tmp/lora",
    )
    base.update(over)
    return AppConfig(**base)


def test_quest_ports_fake_provider_builds():
    ports = build_quest_ports(_cfg(quest_llm_provider="fake"))
    assert ports.llm is not None


def test_todo_generate_ports_openai_builds():
    ports = build_todo_generate_ports(_cfg(llm_provider="openai"))
    assert ports.llm is not None


# ---------------------------------------------------------------------------
# build_todo_multiturn_ports
# ---------------------------------------------------------------------------

def test_build_todo_multiturn_ports_openai():
    ports = build_todo_multiturn_ports(_cfg(llm_provider="openai"))
    assert ports.llm is not None


# ---------------------------------------------------------------------------
# build_commit_ports
# ---------------------------------------------------------------------------

def test_build_commit_ports_returns_ports():
    ports = build_commit_ports(_cfg(), remaining_daily_quota=3)
    assert ports.repository is not None
    assert ports.quest_counter is not None
    assert ports.quest_dispatch is not None


def test_build_commit_ports_quest_counter_remaining():
    ports = build_commit_ports(_cfg(), remaining_daily_quota=7)
    assert ports.quest_counter.remaining == 7


def test_build_commit_ports_zero_quota():
    ports = build_commit_ports(_cfg(), remaining_daily_quota=0)
    assert ports.quest_counter.remaining == 0


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------

def test_get_config_returns_state_config():
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
    content = b"hello image bytes"
    key = "uploads/test_image.png"
    file_path = tmp_path / key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)

    cfg = _cfg(local_storage_root=tmp_path)
    result = await fetch_source_bytes(cfg, key=key, content_type="image/png")
    assert result == content


async def test_fetch_source_bytes_local_nested_key(tmp_path):
    content = b"\x89PNG\r\n\x1a\n"
    key = "a/b/c/img.png"
    (tmp_path / "a" / "b" / "c").mkdir(parents=True, exist_ok=True)
    (tmp_path / key).write_bytes(content)

    cfg = _cfg(local_storage_root=tmp_path)
    result = await fetch_source_bytes(cfg, key=key, content_type="image/png")
    assert result == content


# ---------------------------------------------------------------------------
# midm branch — build_quest_ports and build_todo_generate_ports
# (MidmLLM is a @dataclass; __init__ only stores fields, no network call)
# ---------------------------------------------------------------------------

def test_build_quest_ports_midm_builds():
    ports = build_quest_ports(
        _cfg(
            quest_llm_provider="midm",
            midm_base_url="http://midm-host/v1",
            midm_model="midm-bilingual-instruct",
            midm_api_key="EMPTY",
        )
    )
    assert ports.llm is not None


def test_build_todo_generate_ports_midm_builds():
    ports = build_todo_generate_ports(
        _cfg(
            llm_provider="midm",
            midm_base_url="http://midm-host/v1",
            midm_model="midm-bilingual-instruct",
            midm_api_key="EMPTY",
        )
    )
    assert ports.llm is not None


def test_build_todo_multiturn_ports_midm_builds():
    ports = build_todo_multiturn_ports(
        _cfg(
            llm_provider="midm",
            midm_base_url="http://midm-host/v1",
            midm_model="midm-bilingual-instruct",
            midm_api_key="EMPTY",
        )
    )
    assert ports.llm is not None
