from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest


WORKER_ROOT = Path(__file__).resolve().parents[2] / "runpod_workers" / "image_gen"
sys.path.insert(0, str(WORKER_ROOT))

worker_handler = importlib.import_module("runpod_workers.image_gen.handler")


@pytest.mark.parametrize(
    ("mode", "module_name", "mode_input"),
    [
        ("image_character", "pipelines.image_character.handler", {"image": "base64"}),
        ("text_character", "pipelines.text_character.handler", {"persona": "yellow duck"}),
        ("feed", "pipelines.feed.handler", {"appearance": {}, "quest_en": "a walk"}),
    ],
)
def test_process_job_routes_to_mode_handler(monkeypatch, mode, module_name, mode_input):
    fake_module = types.ModuleType(module_name)
    fake_module.process_job = lambda job: {"status": "done", "received": job["input"]}
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    job_input = {"mode": mode, "seed": 7, **mode_input}
    result = worker_handler.process_job({"input": job_input})

    assert result == {
        "status": "done",
        "mode": mode,
        "received": job_input,
    }


def test_process_job_accepts_supported_alias(monkeypatch):
    module_name = "pipelines.text_character.handler"
    fake_module = types.ModuleType(module_name)
    fake_module.process_job = lambda job: {"status": "done"}
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    assert worker_handler.process_job({"input": {"mode": "text"}})["mode"] == "text_character"


def test_handler_returns_invalid_input_error():
    result = worker_handler.handler({"input": {}})

    assert result["status"] == "failed"
    assert result["code"] == "invalid_input"
