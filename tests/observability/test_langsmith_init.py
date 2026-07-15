import os
import pytest
from agents._shared.observability.langsmith import init_langsmith, langsmith_enabled


def _clear(monkeypatch):
    for k in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT"):
        monkeypatch.delenv(k, raising=False)


def test_disabled_without_key(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")  # 키 없음
    assert langsmith_enabled() is False
    assert init_langsmith() is False


def test_disabled_without_flag(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_x")  # 플래그 없음
    assert init_langsmith() is False


def test_enabled_sets_defaults(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_x")
    assert init_langsmith() is True
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://api.smith.langchain.com"
    assert os.environ["LANGSMITH_PROJECT"] == "mongle-planner"
