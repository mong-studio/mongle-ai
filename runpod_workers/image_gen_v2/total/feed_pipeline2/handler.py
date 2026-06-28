"""RunPod Serverless handler for appearance-JSON-to-feed generation."""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any

try:
    import runpod
except ModuleNotFoundError:
    runpod = None

from total.shared.character_profile import normalize_profile
from .pipeline import generate, load_pipeline, unload_pipeline


LOGGER = logging.getLogger("total.feed_pipeline2")
_LOCK = threading.Lock()
_PIPE = None
MAX_QUEST_LENGTH = int(os.environ.get("MAX_QUEST_LENGTH", "1000"))
APP_ROOT = Path(__file__).resolve().parents[2]


def encode_png(image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _drop_pipeline() -> None:
    global _PIPE
    if _PIPE is not None:
        unload_pipeline(_PIPE)
        _PIPE = None


def _get_pipeline():
    global _PIPE
    if _PIPE is None:
        _PIPE = load_pipeline()
    return _PIPE


def _translate_quest(quest_ko: str) -> str:
    """Use a short-lived VLM process so all translation VRAM is reclaimed."""
    with tempfile.TemporaryDirectory(prefix="feed_translation_") as temp_dir:
        batch_path = Path(temp_dir) / "batch.json"
        batch_path.write_text(
            json.dumps([{"name": "request", "quest_ko": quest_ko}], ensure_ascii=False),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, "-m", "total.feed_pipeline2.vlm_worker", str(batch_path)],
            cwd=str(APP_ROOT),
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            check=False,
        )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"quest translation failed with exit code {proc.returncode}")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    return result[0]["quest_en"]


def process_job(job: dict[str, Any]) -> dict[str, Any]:
    job_input = job.get("input") or {}
    profile = normalize_profile(job_input.get("appearance"))
    quest_en = job_input.get("quest_en")
    quest_ko = job_input.get("quest_ko")
    if quest_en is not None and (not isinstance(quest_en, str) or not quest_en.strip()):
        raise ValueError("input.quest_en must be a non-empty string")
    if quest_ko is not None and (not isinstance(quest_ko, str) or not quest_ko.strip()):
        raise ValueError("input.quest_ko must be a non-empty string")
    if not quest_en and not quest_ko:
        raise ValueError("input.quest_en or input.quest_ko is required")
    quest_text = (quest_en or quest_ko).strip()
    if len(quest_text) > MAX_QUEST_LENGTH:
        raise ValueError(f"quest must be at most {MAX_QUEST_LENGTH} characters")

    seed = int(job_input.get("seed", 42))
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("input.seed must be between 0 and 4294967295")

    with _LOCK:
        if not quest_en:
            _drop_pipeline()
            quest_en = _translate_quest(quest_ko.strip())
        else:
            quest_en = quest_en.strip()
        image = generate(profile, quest_en, _get_pipeline(), seed=seed)

    return {
        "status": "done",
        "image": encode_png(image),
        "appearance": profile,
        "quest_ko": quest_ko,
        "quest_en": quest_en,
        "width": image.width,
        "height": image.height,
        "seed": seed,
    }


def handler(job: dict[str, Any]) -> dict[str, Any]:
    try:
        return process_job(job)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc), "code": "invalid_input"}
    except Exception as exc:
        LOGGER.error("Feed pipeline failed: %s\n%s", exc, traceback.format_exc())
        return {"status": "failed", "error": "Feed generation failed", "code": "generation_failed"}


def main() -> None:
    if runpod is None:
        raise RuntimeError("runpod is required to start the Serverless worker")
    if os.environ.get("PRELOAD_MODELS", "false").lower() == "true":
        _get_pipeline()
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
