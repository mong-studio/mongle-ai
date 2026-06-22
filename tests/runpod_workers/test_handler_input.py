import base64
import importlib
import sys
import types

import pytest


def _load_handler(monkeypatch, capture):
    fake = types.ModuleType("pipeline")

    class _P:
        def generate(self, *, adapter, source_image_bytes, prompt, scene_prompt):
            capture.update(
                adapter=adapter,
                prompt=prompt,
                scene_prompt=scene_prompt,
                has_src=source_image_bytes is not None,
            )
            return b"PNG"

    fake.get_pipeline = lambda: _P()
    monkeypatch.setitem(sys.modules, "pipeline", fake)
    monkeypatch.setitem(
        sys.modules,
        "runpod",
        types.SimpleNamespace(
            serverless=types.SimpleNamespace(start=lambda *_a, **_k: None)
        ),
    )
    sys.path.insert(0, "runpod_workers/image_gen")
    return importlib.reload(importlib.import_module("handler"))


def test_handler_passes_scene_prompt(monkeypatch):
    cap = {}
    h = _load_handler(monkeypatch, cap)
    out = h.handler(
        {
            "input": {
                "adapter": "feed",
                "prompt": "char",
                "scene_prompt": "bg",
                "source_image_b64": base64.b64encode(b"x").decode(),
            }
        }
    )
    assert base64.b64decode(out["image_b64"]) == b"PNG"
    assert cap == {"adapter": "feed", "prompt": "char", "scene_prompt": "bg", "has_src": True}


def test_handler_requires_adapter(monkeypatch):
    h = _load_handler(monkeypatch, {})
    with pytest.raises(ValueError):
        h.handler({"input": {"prompt": "x"}})
