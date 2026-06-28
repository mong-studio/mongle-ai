"""Exercise the RunPod request contract without loading inference models."""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image

WORKER_ROOT = Path(__file__).resolve().parents[2] / "runpod_workers" / "image_gen"
sys.path.insert(0, str(WORKER_ROOT))

from pipelines.image_character.handler import process_job


def _sample_b64() -> str:
    image = Image.new("RGB", (128, 96), (240, 120, 80))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class _FakeRuntime:
    def process(self, image: Image.Image, seed: int):
        return {
            "image": Image.new("RGB", (1024, 1024), (255, 255, 255)),
            "mascot": Image.new("RGB", (512, 512), (255, 255, 255)),
            "appearance": {"character_type": "plush mascot"},
            "prompt": "test prompt",
            "metadata": {"seed": seed, "model_mode": "test"},
        }


def test_process_job_contract() -> None:
    with patch("pipelines.image_character.handler.get_default_runtime", return_value=_FakeRuntime()):
        response = process_job({"input": {"image": _sample_b64(), "seed": 42, "debug": True}})
    assert response["status"] == "done"
    assert response["width"] == 1024 and response["height"] == 1024
    assert response["appearance"]["character_type"] == "plush mascot"
    assert base64.b64decode(response["image"])
