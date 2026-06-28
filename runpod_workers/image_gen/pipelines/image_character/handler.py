"""RunPod handler for photo-to-character generation."""

from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import os
import traceback
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import runpod
except ModuleNotFoundError:  # Allows contract tests before installing RunPod SDK.
    runpod = None

from pipelines.shared.character_profile import normalize_profile


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
LOGGER = logging.getLogger("pipelines.image_character")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(7 * 1024 * 1024)))
RETURN_DEBUG_DEFAULT = os.environ.get("RETURN_DEBUG_DEFAULT", "false").lower() == "true"
Image.MAX_IMAGE_PIXELS = int(os.environ.get("MAX_INPUT_PIXELS", "40000000"))


def get_default_runtime():
    from .pipeline import get_default_runtime as load_runtime

    return load_runtime()


def normalize_input_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    if width < 64 or height < 64:
        raise ValueError("Input image must be at least 64x64 pixels")
    if width * height > Image.MAX_IMAGE_PIXELS:
        raise ValueError(f"Input image exceeds the {Image.MAX_IMAGE_PIXELS} pixel limit")
    return image.convert("RGB")


def decode_image(data: str) -> Image.Image:
    if not isinstance(data, str) or not data.strip():
        raise ValueError("input.image must be a non-empty base64 string")
    payload = data.split(",", 1)[1] if data.startswith("data:image") and "," in data else data
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("input.image is not valid base64") from exc
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Uploaded image exceeds {MAX_UPLOAD_BYTES} bytes")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as image:
            return normalize_input_image(image.copy())
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("input.image must contain a valid JPG, PNG, or WEBP image") from exc


def encode_png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def process_job(job: dict[str, Any]) -> dict[str, Any]:
    job_input = job.get("input") or {}
    image = decode_image(job_input.get("image", ""))
    seed = int(job_input.get("seed", 42))
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("input.seed must be between 0 and 4294967295")
    debug_value = job_input.get("debug", RETURN_DEBUG_DEFAULT)
    if not isinstance(debug_value, bool):
        raise ValueError("input.debug must be true or false")
    debug = debug_value

    result = get_default_runtime().process(image, seed=seed)
    response: dict[str, Any] = {
        "status": "done",
        "image": encode_png(result["image"]),
        "appearance": normalize_profile(result["appearance"]),
        "width": result["image"].width,
        "height": result["image"].height,
        "seed": seed,
        "metadata": result["metadata"],
    }
    if debug:
        response["mascot"] = encode_png(result["mascot"])
        response["prompt"] = result["prompt"]
    return response


def handler(job: dict[str, Any]) -> dict[str, Any]:
    try:
        return process_job(job)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc), "code": "invalid_input"}
    except Exception as exc:
        LOGGER.error("Pipeline request failed: %s\n%s", exc, traceback.format_exc())
        return {"status": "failed", "error": "Image generation failed", "code": "generation_failed"}


def main() -> None:
    if runpod is None:
        raise RuntimeError("runpod is required to start the Serverless worker")
    runtime = get_default_runtime()
    LOGGER.info("GPU=%s VRAM=%sGB mode=%s", runtime.info.gpu_name, runtime.info.vram_gb, runtime.info.model_mode)
    if os.environ.get("PRELOAD_MODELS", "true").lower() == "true":
        runtime.warmup()
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
