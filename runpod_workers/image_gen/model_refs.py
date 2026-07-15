"""Shared Hugging Face model references for the image generation worker."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRef:
    repo_id: str
    revision: str | None = None


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def _revision(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip() or None


SDXL_BASE = ModelRef(
    repo_id=_env("SDXL_BASE_MODEL", "stabilityai/stable-diffusion-xl-base-1.0"),
    revision=_revision(
        "SDXL_BASE_MODEL_REVISION",
        "462165984030d82259a11f4367a4eed129e94a7b",
    ),
)
CONTROLNET_CANNY = ModelRef(
    repo_id=_env("CONTROLNET_CANNY_MODEL", "diffusers/controlnet-canny-sdxl-1.0"),
    revision=_revision(
        "CONTROLNET_CANNY_MODEL_REVISION",
        "eb115a19a10d14909256db740ed109532ab1483c",
    ),
)
LCM_LORA = ModelRef(
    repo_id=_env("LCM_LORA_SOURCE", "latent-consistency/lcm-lora-sdxl"),
    revision=_revision("LCM_LORA_REVISION", "a18548dd4956b174ec5b0d78d340c8dae0a129cd"),
)
QWEN2_VL = ModelRef(
    repo_id=_env("QWEN2VL_MODEL", "Qwen/Qwen2-VL-7B-Instruct"),
    revision=_revision("QWEN2VL_MODEL_REVISION", "eed13092ef92e448dd6875b2a00151bd3f7db0ac"),
)
QWEN25_VL = ModelRef(
    repo_id=_env("QWEN25VL_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"),
    revision=_revision("QWEN25VL_MODEL_REVISION", "cc594898137f460bfe9f0759e9844b3ce807cfb5"),
)
