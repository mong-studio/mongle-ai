import importlib
import sys
import types

import pytest


def _load_pipeline(monkeypatch, env):
    for k in ("LORA_CHARACTER_REPO", "LORA_BG_REPO"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # 무거운 diffusers import 회피 — 모드 클래스를 가벼운 가짜로 대체
    for name, attr in [
        ("character_mode", "CharacterMode"),
        ("bg_mode", "BgMode"),
        ("feed_mode", "FeedMode"),
    ]:
        mod = types.ModuleType(name)

        def _make(label):
            class _M:
                def __init__(self, **kw):
                    self.label = label

                def generate(self, *, source_image_bytes=None, prompt=None, scene_prompt=None):
                    return f"{label}:{prompt}:{scene_prompt}".encode()

            return _M

        setattr(mod, attr, _make(name))
        monkeypatch.setitem(sys.modules, name, mod)
    sys.path.insert(0, "runpod_workers/image_gen")
    return importlib.reload(importlib.import_module("pipeline"))


def test_feed_registered_when_both_loras_present(monkeypatch):
    p = _load_pipeline(monkeypatch, {"LORA_CHARACTER_REPO": "c", "LORA_BG_REPO": "b"})
    out = p.get_pipeline().generate(adapter="feed", prompt="char", scene_prompt="bg")
    assert out == b"feed_mode:char:bg"


def test_feed_unavailable_without_bg(monkeypatch):
    p = _load_pipeline(monkeypatch, {"LORA_CHARACTER_REPO": "c"})
    with pytest.raises(ValueError):
        p.get_pipeline().generate(adapter="feed", prompt="x", scene_prompt="y")


def test_character_adapter_still_works(monkeypatch):
    p = _load_pipeline(monkeypatch, {"LORA_CHARACTER_REPO": "c"})
    out = p.get_pipeline().generate(adapter="character", prompt="p")
    assert out == b"character_mode:p:None"
