"""RunPod Serverless handler for the Mongle image pipelines.

Input examples:

    {"input": {"mode": "image_character", "image": "<base64>", "seed": 42}}
    {"input": {"mode": "text_character", "persona": "노란 오리 인형", "seed": 42}}
    {"input": {"mode": "feed", "appearance": {...}, "quest_ko": "공원 산책", "seed": 42}}

The character modes return a transparent-background character PNG plus the
canonical appearance JSON. The feed mode consumes that appearance JSON.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

try:
    import runpod
except ModuleNotFoundError:
    runpod = None


LOGGER = logging.getLogger("image_gen")

MODE_ALIASES = {
    "image": "image_character",
    "photo": "image_character",
    "image_character": "image_character",
    "text": "text_character",
    "persona": "text_character",
    "text_character": "text_character",
    "feed": "feed",
    "feed_generation": "feed",
}


def _mode(job_input: dict[str, Any]) -> str:
    raw = job_input.get("mode") or job_input.get("adapter")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("input.mode is required: image_character, text_character, or feed")
    mode = MODE_ALIASES.get(raw.strip().lower())
    if mode is None:
        raise ValueError(f"unsupported input.mode: {raw!r}")
    return mode


def process_job(job: dict[str, Any]) -> dict[str, Any]:
    job_input = job.get("input") or {}
    mode = _mode(job_input)

    if mode == "image_character":
        from pipelines.image_character.handler import process_job as process_image

        image = job_input.get("image") or job_input.get("source_image_b64")
        result = process_image({"input": {**job_input, "image": image}})
    elif mode == "text_character":
        from pipelines.text_character.handler import process_job as process_text

        persona = job_input.get("persona") or job_input.get("prompt")
        result = process_text({"input": {**job_input, "persona": persona}})
    else:
        from pipelines.feed.handler import process_job as process_feed

        result = process_feed({"input": job_input})

    if isinstance(result, dict):
        result.setdefault("mode", mode)
    return result


def handler(job: dict[str, Any]) -> dict[str, Any]:
    try:
        return process_job(job)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc), "code": "invalid_input"}
    except Exception as exc:
        LOGGER.error("image_gen failed: %s\n%s", exc, traceback.format_exc())
        return {"status": "failed", "error": "image generation failed", "code": "generation_failed"}


def main() -> None:
    if runpod is None:
        raise RuntimeError("runpod is required to start the Serverless worker")
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
