#!/usr/bin/env bash
# RunPod GPU 팟 1회 셋업.
#
# 핵심 원칙: torch / torchvision 는 팟 기본 설치본을 그대로 쓴다 (직접 재설치 금지 — CUDA 빌드가 어긋남).
# torchvision 은 torch 와 버전이 강하게 엮여 불일치의 주범이며, 텍스트 LLM 평가엔 불필요하므로 제거한다.
set -euo pipefail

echo "[1/3] torchvision 제거 (torch↔torchvision 불일치 원천 차단)"
python -m pip uninstall -y torchvision || true

echo "[2/3] 평가에 필요한 것만 설치 (torch 는 건드리지 않음)"
python -m pip install -U \
  "transformers==5.9.0" "tokenizers==0.22.2" accelerate safetensors sentencepiece protobuf \
  openai pandas tqdm python-dotenv

echo "[3/3] 검증"
python - <<'PY'
import importlib.util
assert importlib.util.find_spec("torchvision") is None, "torchvision 아직 있음 — 커널/셸 재시작 후 다시"
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa
import torch
print("OK | torch", torch.__version__, "| cuda", torch.cuda.is_available())
PY

echo "완료 → Jupyter 에서 notebooks/model_evaluation.ipynb 실행"
