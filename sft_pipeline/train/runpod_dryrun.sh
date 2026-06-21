#!/usr/bin/env bash
set -euo pipefail

# 파인튜닝 첫 dry-run 한 방 스크립트. RunPod GPU 파드의 "저장소 루트"에서 실행한다.
#   bash sft_pipeline/train/runpod_dryrun.sh
#
# 입력: 본인이 만든 train/valid jsonl (HANDOVER.ipynb 섹션 7-4 split 산출물).
# env 오버라이드 예: EPOCHS=1.0 OUT=outputs/v1 bash sft_pipeline/train/runpod_dryrun.sh

TRAIN="${TRAIN:-sft_pipeline/data/generated/train.jsonl}"
VALID="${VALID:-sft_pipeline/data/generated/valid.jsonl}"
OUT="${OUT:-outputs/my-planner-lora}"
MODEL="${MODEL:-Qwen/Qwen2.5-7B-Instruct}"
EPOCHS="${EPOCHS:-0.10}"            # dry-run=0.10(빠른 점검) / 본 학습=1.0
MAX_SEQ_LEN="${MAX_SEQ_LEN:-2048}"
BATCH="${BATCH:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-4}"
LR="${LR:-2e-4}"

echo "[dryrun] cwd=$(pwd) train=${TRAIN} out=${OUT} model=${MODEL} epochs=${EPOCHS}"

# 1) 필수 파일 확인
for f in sft_pipeline/train/train_lora.py sft_pipeline/train/dataset.py \
         sft_pipeline/train/requirements.txt "${TRAIN}" "${VALID}"; do
  [ -f "${f}" ] || { echo "[dryrun] 누락된 파일: ${f}"; exit 1; }
done
echo "[dryrun] 필수 파일 OK"

# 2) GPU(CUDA) 확인 — 없으면 중단 (로컬 macOS 에서는 학습 불가)
python3 - <<'PY'
import torch
print("[dryrun] torch", torch.__version__, "/ cuda", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("[dryrun] CUDA GPU 가 필요합니다 (RunPod 등)")
print("[dryrun] gpu", torch.cuda.get_device_name(0))
PY

# 3) 학습 의존성 설치 (GPU 전용: unsloth·peft·trl·bitsandbytes)
python3 -m pip install -U pip
python3 -m pip install -r sft_pipeline/train/requirements.txt

# 4) 데이터 검증 (형식 + 플랜 정합성). 여기서 막히면 데이터부터 고친다.
python3 -m sft_pipeline.build.lib.validate_dataset --in "${TRAIN}"
python3 -m sft_pipeline.build.lib.validate_dataset --in "${VALID}"

# 5) LoRA 학습
#    train_lora.py 는 unsloth 를 trl 보다 "먼저" import 한다 (EOS_TOKEN 크래시 방지 — TROUBLESHOOTING.md).
python3 -m sft_pipeline.train.train_lora \
  --train "${TRAIN}" --valid "${VALID}" --out "${OUT}" --model "${MODEL}" \
  --epochs "${EPOCHS}" --max-seq-len "${MAX_SEQ_LEN}" \
  --batch "${BATCH}" --grad-accum "${GRAD_ACCUM}" --lr "${LR}"

# 6) 학습 후 점검: 어댑터를 추론 파서로 채점 (배치 평가 — parse 성공률·distractor 거절률)
python3 -m sft_pipeline.eval.chat_eval --adapter "${OUT}" --out "${OUT}/eval_report.json" \
  || echo "[dryrun] eval 실패/스킵 — 수동으로 'python3 -m sft_pipeline.eval.chat_eval --adapter ${OUT}' 실행"

echo "[dryrun] 완료: ${OUT}  (어댑터 + eval_report.json)"
