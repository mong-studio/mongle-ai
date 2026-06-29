"""Build-time: Qwen2.5-7B-Instruct 베이스 모델 사전 다운로드.

LoRA(LORA_REPO_ID)는 런타임에 HF_TOKEN 으로 받는다.
HF 가 무인증 대량 요청에 429(rate limit)를 내므로 백오프 재시도하고,
HF_TOKEN 이 빌드에 주입되면 인증해 레이트리밋을 완화한다.
(CI 빌드에서 unauthenticated 429 로 실패한 이력 — requirements 변경이 이 레이어
캐시를 무효화해 15GB 재다운로드가 트리거됐을 때 발생)
"""
from __future__ import annotations

import os
import time

from huggingface_hub import snapshot_download
from huggingface_hub.errors import HfHubHTTPError

HF_HOME = os.environ.get("HF_HOME", "/app/hf-cache")
HF_TOKEN = os.environ.get("HF_TOKEN") or None
# pipeline.py 와 같은 env 를 쓴다. Dockerfile 이 build-arg→ENV 로 주입하면
# 빌드 때 굽는 모델과 런타임에 로드하는 모델이 항상 일치한다(기본 Qwen).
BASE_MODEL = os.environ.get("LLM_BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct").strip()
BASE_MODEL_REVISION = (
    os.environ.get(
        "LLM_BASE_MODEL_REVISION", "a09a35458c702b33eeacc393d103063234e8bc28"
    ).strip()
    or None
)


def download_base(*, attempts: int = 5, base_delay: int = 15) -> None:
    """429 에 지수 백오프 재시도. 동시 요청을 줄여 레이트리밋 확률을 낮춘다."""
    for attempt in range(attempts):
        try:
            snapshot_download(
                BASE_MODEL,
                revision=BASE_MODEL_REVISION,
                cache_dir=HF_HOME,
                token=HF_TOKEN,
                max_workers=2,
            )
            return
        except HfHubHTTPError as err:
            status = getattr(err.response, "status_code", None)
            if status == 429 and attempt < attempts - 1:
                delay = base_delay * (2**attempt)
                print(f"HF 429 rate limit — {delay}s 후 재시도 ({attempt + 1}/{attempts})")
                time.sleep(delay)
                continue
            raise


print(f"베이스 모델 다운로드: {BASE_MODEL}")
download_base()
print("완료")
