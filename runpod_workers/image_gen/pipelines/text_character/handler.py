"""RunPod Serverless handler for text character generation."""

from __future__ import annotations

import base64
import io
import logging
import os
import threading
import traceback
from typing import Any

try:
    import runpod
except ModuleNotFoundError:
    runpod = None

from pipelines.shared.character_profile import normalize_profile
from .pipeline import run_pipeline


LOGGER = logging.getLogger("pipelines.text_character")
_LOCK = threading.Lock()
MAX_PERSONA_LENGTH = int(os.environ.get("MAX_PERSONA_LENGTH", "2000"))


def encode_png(image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def process_job(job: dict[str, Any]) -> dict[str, Any]:
    job_input = job.get("input") or {}
    persona = job_input.get("persona")
    if not isinstance(persona, str) or not persona.strip():
        raise ValueError("input.persona must be a non-empty string")
    persona = persona.strip()
    if len(persona) > MAX_PERSONA_LENGTH:
        raise ValueError(f"input.persona must be at most {MAX_PERSONA_LENGTH} characters")

    # prompt_en 이 오면(이미 영어 태그) 워커는 Qwen2-VL 번역을 건너뛴다. 비었으면 기존 번역 경로.
    prompt_en = job_input.get("prompt_en")
    if prompt_en is not None and (not isinstance(prompt_en, str) or not prompt_en.strip()):
        raise ValueError("input.prompt_en must be a non-empty string when provided")
    prompt_en = prompt_en.strip() if isinstance(prompt_en, str) and prompt_en.strip() else None

    seed = int(job_input.get("seed", 42))
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("input.seed must be between 0 and 4294967295")

    with _LOCK:
        result = run_pipeline(
            persona_ko=persona,
            prompt_en=prompt_en,
            lcm=bool(job_input.get("lcm", True)),
            lora_scale=float(job_input.get("lora_scale", 0.9)),
            steps=int(job_input.get("steps", 8)),
            seed=seed,
        )

    image = result["result_nobg"]
    return {
        "status": "done",
        "image": encode_png(image),
        "appearance": normalize_profile(result["appearance"]),
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
        LOGGER.error("Text pipeline failed: %s\n%s", exc, traceback.format_exc())
        return {"status": "failed", "error": "Character generation failed", "code": "generation_failed"}


def main() -> None:
    if runpod is None:
        raise RuntimeError("runpod is required to start the Serverless worker")
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
