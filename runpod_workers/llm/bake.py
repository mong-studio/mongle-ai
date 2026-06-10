"""Build-time: Qwen2.5-7B-Instruct 베이스 모델 사전 다운로드.

LoRA(LORA_REPO_ID)는 private repo 일 수 있으므로 런타임에 HF_TOKEN 으로 받는다.
"""
from __future__ import annotations

import os

from huggingface_hub import snapshot_download
from transformers import AutoTokenizer

HF_HOME = os.environ.get("HF_HOME", "/app/hf-cache")
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"

print(f"베이스 모델 다운로드: {BASE_MODEL}")
snapshot_download(BASE_MODEL, cache_dir=HF_HOME)
AutoTokenizer.from_pretrained(BASE_MODEL, cache_dir=HF_HOME, trust_remote_code=True)
print("완료")
