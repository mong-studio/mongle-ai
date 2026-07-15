"""Build-time download of shared image-generation model weights."""

from __future__ import annotations

import os
import time

from huggingface_hub import snapshot_download
from huggingface_hub.errors import HfHubHTTPError

from model_refs import CONTROLNET_CANNY, LCM_LORA, SDXL_BASE, ModelRef


HF_HOME = os.environ.get("HF_HOME", "/app/hf-cache")
HF_TOKEN = os.environ.get("HF_TOKEN") or None
BAKE_TARGETS: tuple[ModelRef, ...] = (SDXL_BASE, CONTROLNET_CANNY, LCM_LORA)


def download_model(ref: ModelRef, *, attempts: int = 5, base_delay: int = 15) -> None:
    """Download with bounded 429 backoff for unattended CI builds."""
    for attempt in range(attempts):
        try:
            snapshot_download(
                ref.repo_id,
                revision=ref.revision,
                cache_dir=HF_HOME,
                token=HF_TOKEN,
                max_workers=2,
            )
            return
        except HfHubHTTPError as err:
            status = getattr(err.response, "status_code", None)
            if status == 429 and attempt < attempts - 1:
                delay = base_delay * (2**attempt)
                print(
                    f"HF 429 rate limit for {ref.repo_id} — "
                    f"{delay}s 후 재시도 ({attempt + 1}/{attempts})"
                )
                time.sleep(delay)
                continue
            raise


for target in BAKE_TARGETS:
    revision = target.revision or "default"
    print(f"모델 다운로드: {target.repo_id} @ {revision}")
    download_model(target)

print("완료")

