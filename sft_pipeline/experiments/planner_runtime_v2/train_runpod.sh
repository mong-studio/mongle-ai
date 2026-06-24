#!/usr/bin/env bash
set -euo pipefail

# 기존 planner LoRA와 완전히 분리된 신규 runtime-v2 실험.
# 저장소 루트에서 실행한다. 기존 HF repo나 outputs 디렉터리를 덮어쓰지 않는다.

DATA="${DATA:-sft_pipeline/experiments/planner_runtime_v2/data/planner_runtime_v2_gold_300.jsonl}"
EXPERIMENT_ROOT="${EXPERIMENT_ROOT:-outputs/planner-runtime-v2}"
TRAIN="${EXPERIMENT_ROOT}/data/train.jsonl"
VALID="${EXPERIMENT_ROOT}/data/valid.jsonl"
ADAPTER_OUT="${EXPERIMENT_ROOT}/adapter"
REPORT_OUT="${EXPERIMENT_ROOT}/eval_report.json"
MODEL="${MODEL:-Qwen/Qwen2.5-7B-Instruct}"
EPOCHS="${EPOCHS:-1.0}"
MAX_SEQ_LEN="${MAX_SEQ_LEN:-4096}"
BATCH="${BATCH:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-4}"
LR="${LR:-2e-4}"
RUN_EVAL="${RUN_EVAL:-1}"

if [ -e "${EXPERIMENT_ROOT}" ]; then
  echo "[runtime-v2] ${EXPERIMENT_ROOT}가 이미 존재합니다. 새 EXPERIMENT_ROOT를 지정하세요."
  exit 1
fi

for file in "${DATA}" sft_pipeline/train/train_lora.py \
  sft_pipeline/experiments/planner_runtime_v2/evaluate.py; do
  [ -f "${file}" ] || { echo "[runtime-v2] 누락: ${file}"; exit 1; }
done

python3 - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("[runtime-v2] CUDA GPU가 필요합니다")
print("[runtime-v2] GPU:", torch.cuda.get_device_name(0))
PY

ROWS="$(grep -cve '^[[:space:]]*$' "${DATA}")"
if [ "${ROWS}" -ne 300 ]; then
  echo "[runtime-v2] 데이터는 정확히 300건이어야 합니다: 실제 ${ROWS}건"
  exit 1
fi

mkdir -p "${EXPERIMENT_ROOT}/data"
python3 -m pip install -U pip
python3 -m pip install -r sft_pipeline/train/requirements.txt

python3 -m sft_pipeline.build.lib.validate_dataset --in "${DATA}"
python3 -m sft_pipeline.build.lib.coherence_eval \
  --in "${DATA}" --out "${EXPERIMENT_ROOT}/data/coherence_report.json"
python3 -m sft_pipeline.build.lib.split_dataset \
  --in "${DATA}" --out-train "${TRAIN}" --out-valid "${VALID}" \
  --ratio 0.9 --seed 42
python3 -m sft_pipeline.build.lib.validate_dataset --in "${TRAIN}"
python3 -m sft_pipeline.build.lib.validate_dataset --in "${VALID}"

python3 -m sft_pipeline.train.train_lora \
  --train "${TRAIN}" --valid "${VALID}" --out "${ADAPTER_OUT}" \
  --model "${MODEL}" --epochs "${EPOCHS}" --max-seq-len "${MAX_SEQ_LEN}" \
  --batch "${BATCH}" --grad-accum "${GRAD_ACCUM}" --lr "${LR}"

if [ "${RUN_EVAL}" = "1" ]; then
  python3 -m sft_pipeline.experiments.planner_runtime_v2.evaluate \
    --adapter "${ADAPTER_OUT}" --base-model "${MODEL}" --out "${REPORT_OUT}"
else
  echo "[runtime-v2] RUN_EVAL=0: 모델 평가는 생략했습니다. 배포 승격에 사용하지 마세요."
fi

cat <<EOF
[runtime-v2] 완료
  기존 어댑터: 변경하지 않음
  신규 어댑터: ${ADAPTER_OUT}
  평가 리포트: ${REPORT_OUT}
EOF
