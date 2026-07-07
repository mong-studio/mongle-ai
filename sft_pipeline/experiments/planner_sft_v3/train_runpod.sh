#!/usr/bin/env bash
# sft_pipeline/experiments/planner_sft_v3/train_runpod.sh
set -euo pipefail

# 기존 planner LoRA 와 완전히 분리된 v3 실험. 저장소 루트에서 실행.
# EXAONE 는 unsloth 미지원 → train_plain.py (표준 transformers+peft) 사용.

DATA="${DATA:-sft_pipeline/experiments/planner_sft_v3/data/planner_sft_v3_gold.jsonl}"
HOLDOUT="${HOLDOUT:-sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl}"
EXPERIMENT_ROOT="${EXPERIMENT_ROOT:-outputs/planner-sft-v3-run1}"
TRAIN="${EXPERIMENT_ROOT}/data/train.jsonl"
VALID="${EXPERIMENT_ROOT}/data/valid.jsonl"
ADAPTER_OUT="${EXPERIMENT_ROOT}/adapter"
REPORT_OUT="${EXPERIMENT_ROOT}/eval_report.json"
TRAIN_LOG="${EXPERIMENT_ROOT}/train_log.txt"
MODEL="${MODEL:-LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct}"
EPOCHS="${EPOCHS:-1.0}"
BATCH="${BATCH:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"
LR="${LR:-2e-4}"
MEMORIZATION_FLOOR="${MEMORIZATION_FLOOR:-0.3}"   # 스펙 §6: 이보다 낮으면 암기 경고
RUN_EVAL="${RUN_EVAL:-1}"

if [ -e "${EXPERIMENT_ROOT}" ]; then
  echo "[sft-v3] ${EXPERIMENT_ROOT} 가 이미 존재합니다. 새 EXPERIMENT_ROOT 를 지정하세요."
  exit 1
fi
for file in "${DATA}" "${HOLDOUT}" sft_pipeline/train/train_plain.py \
  sft_pipeline/experiments/planner_sft_v3/evaluate.py; do
  [ -f "${file}" ] || { echo "[sft-v3] 누락: ${file}"; exit 1; }
done

python3 - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("[sft-v3] CUDA GPU가 필요합니다")
print("[sft-v3] GPU:", torch.cuda.get_device_name(0))
PY

ROWS="$(grep -cve '^[[:space:]]*$' "${DATA}")"
if [ "${ROWS}" -lt 700 ] || [ "${ROWS}" -gt 1000 ]; then
  echo "[sft-v3] 데이터는 700~1000건이어야 합니다(증류 필터 후): 실제 ${ROWS}건"
  exit 1
fi

mkdir -p "${EXPERIMENT_ROOT}/data"
python3 -m pip install -U pip
python3 -m pip install -r sft_pipeline/train/requirements.txt

python3 -m sft_pipeline.build.lib.validate_dataset --in "${DATA}"
python3 -m sft_pipeline.build.lib.split_dataset \
  --in "${DATA}" --out-train "${TRAIN}" --out-valid "${VALID}" \
  --ratio 0.9 --seed 42
python3 -m sft_pipeline.build.lib.validate_dataset --in "${TRAIN}"
python3 -m sft_pipeline.build.lib.validate_dataset --in "${VALID}"

# tmux 안에서 실행 권장 (SSH 끊김 = SIGKILL). 재실행은 HF_HUB_OFFLINE=1.
python3 -m sft_pipeline.train.train_plain \
  --train "${TRAIN}" --valid "${VALID}" --out "${ADAPTER_OUT}" \
  --model "${MODEL}" --epochs "${EPOCHS}" \
  --batch "${BATCH}" --grad-accum "${GRAD_ACCUM}" --lr "${LR}" \
  2>&1 | tee "${TRAIN_LOG}"

# 암기 경고 가드(스펙 §6): 마지막 train_loss 가 바닥보다 낮으면 승격 금지
FINAL_LOSS="$(grep -oE "'loss': [0-9.]+" "${TRAIN_LOG}" | tail -1 | grep -oE '[0-9.]+' || echo '')"
if [ -n "${FINAL_LOSS}" ]; then
  python3 - "$FINAL_LOSS" "$MEMORIZATION_FLOOR" <<'PY'
import sys
loss, floor = float(sys.argv[1]), float(sys.argv[2])
print(f"[sft-v3] final train_loss={loss}")
if loss < floor:
    raise SystemExit(f"[sft-v3] 암기 경고: train_loss {loss} < {floor} — 데이터 다양성 재점검 후 재학습 (스펙 §6)")
PY
else
  echo "[sft-v3] 경고: train_loss 를 로그에서 찾지 못함 — ${TRAIN_LOG} 수동 확인 필요"
fi

if [ "${RUN_EVAL}" = "1" ]; then
  python3 -m sft_pipeline.experiments.planner_sft_v3.evaluate \
    --adapter "${ADAPTER_OUT}" --base-model "${MODEL}" \
    --holdout "${HOLDOUT}" --out "${REPORT_OUT}"
else
  echo "[sft-v3] RUN_EVAL=0: 평가 생략 — 배포 승격에 사용 금지"
fi

echo "[sft-v3] 완료 — 어댑터 즉시 S3 백업 필수 (Pod ephemeral):"
echo "  tar czf exaone-planner-sft-v3.tgz -C ${ADAPTER_OUT} . && aws s3 cp ..."
