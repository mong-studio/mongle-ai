#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root on a RunPod GPU instance.
#
# Required files:
#   sft_pipeline/data/generated/ipe_hardened_v5_dryrun_train.jsonl
#   sft_pipeline/data/generated/ipe_hardened_v5_dryrun_valid.jsonl
#
# Optional env overrides:
#   MODEL, TRAIN, VALID, OUT, EPOCHS, MAX_SEQ_LEN, BATCH, GRAD_ACCUM, LR,
#   POSTCHECK_N, POSTCHECK_MAX_NEW_TOKENS

TRAIN="${TRAIN:-sft_pipeline/data/generated/ipe_hardened_v5_dryrun_train.jsonl}"
VALID="${VALID:-sft_pipeline/data/generated/ipe_hardened_v5_dryrun_valid.jsonl}"
OUT="${OUT:-outputs/ipe-qwen7b-v3-lora}"
MODEL="${MODEL:-Qwen/Qwen2.5-7B-Instruct}"
EPOCHS="${EPOCHS:-0.10}"
MAX_SEQ_LEN="${MAX_SEQ_LEN:-2048}"
BATCH="${BATCH:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-4}"
LR="${LR:-2e-4}"
POSTCHECK_N="${POSTCHECK_N:-5}"
POSTCHECK_MAX_NEW_TOKENS="${POSTCHECK_MAX_NEW_TOKENS:-512}"

echo "[runpod] cwd=$(pwd)"
echo "[runpod] train=${TRAIN}"
echo "[runpod] valid=${VALID}"
echo "[runpod] out=${OUT}"
echo "[runpod] model=${MODEL}"
echo "[runpod] epochs=${EPOCHS}"

python3 - <<'PY'
from pathlib import Path
for path in [
    Path("sft_pipeline/train/requirements.txt"),
    Path("sft_pipeline/train/train_lora.py"),
    Path("sft_pipeline/train/dataset.py"),
    Path("sft_pipeline/data/generated/ipe_hardened_v5_dryrun_train.jsonl"),
    Path("sft_pipeline/data/generated/ipe_hardened_v5_dryrun_valid.jsonl"),
]:
    if not path.exists():
        raise SystemExit(f"[runpod] missing required file: {path}")
print("[runpod] required files OK")
PY

python3 - <<'PY'
try:
    import torch
except Exception as exc:
    raise SystemExit(f"[runpod] torch import failed: {exc}") from exc
print("[runpod] torch", torch.__version__)
print("[runpod] cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    print("[runpod] gpu", torch.cuda.get_device_name(0))
else:
    raise SystemExit("[runpod] CUDA is required for LoRA dry-run")
PY

python3 -m pip install -U pip
python3 -m pip install -r sft_pipeline/train/requirements.txt

python3 -m sft_pipeline.build.validate_dataset --in "${TRAIN}"
python3 -m sft_pipeline.build.validate_dataset --in "${VALID}"

python3 -m sft_pipeline.train.train_lora \
  --train "${TRAIN}" \
  --valid "${VALID}" \
  --out "${OUT}" \
  --model "${MODEL}" \
  --epochs "${EPOCHS}" \
  --max-seq-len "${MAX_SEQ_LEN}" \
  --batch "${BATCH}" \
  --grad-accum "${GRAD_ACCUM}" \
  --lr "${LR}"

python3 -m sft_pipeline.train.postcheck \
  --valid "${VALID}" \
  --adapter "${OUT}" \
  --n-samples "${POSTCHECK_N}" \
  --max-new-tokens "${POSTCHECK_MAX_NEW_TOKENS}" \
  --out "${OUT}/postcheck_report.json"

echo "[runpod] dry-run complete: ${OUT}"
