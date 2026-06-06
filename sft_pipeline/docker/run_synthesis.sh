#!/usr/bin/env bash
# RunPod 올인원 엔트리포인트.
#   1) vLLM 서버를 백그라운드로 기동 → 2) /health 대기 → 3) download→parse→localize→synthesize
#   → 4) (S3_BUCKET 있으면) S3 업로드.
# 동작은 환경변수로 조정한다. 시크릿(AWS_*)은 RunPod 환경변수로 주입한다.
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen2.5-14B-Instruct}"
PORT="${VLLM_PORT:-8000}"
SAMPLE_LIMIT="${SAMPLE_LIMIT:-1000}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-60}"
TODAY="${TODAY:-}"                              # 비우면 컨테이너의 오늘 날짜 사용
GPU_MEM_UTIL="${GPU_MEMORY_UTILIZATION:-0.90}"
MAX_LEN="${MAX_MODEL_LEN:-8192}"

DATA=/app/sft_pipeline/data
SOURCES="$DATA/sources/ms_latte.json"
PARSED="$DATA/parsed/latte_parsed.csv"
SEEDS="$DATA/seeds/daily_seeds.csv"
OUT="$DATA/generated/daily.jsonl"

echo "[run] starting vLLM serve: $MODEL on :$PORT"
vllm serve "$MODEL" \
  --port "$PORT" \
  --gpu-memory-utilization "$GPU_MEM_UTIL" \
  --max-model-len "$MAX_LEN" &
VLLM_PID=$!

cleanup() { echo "[run] stopping vLLM ($VLLM_PID)"; kill "$VLLM_PID" 2>/dev/null || true; }
trap cleanup EXIT

echo "[run] waiting for vLLM health (max ~20m) ..."
HEALTH_OK=0
for i in $(seq 1 120); do
  if python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:${PORT}/health',timeout=2)" >/dev/null 2>&1; then
    echo "[run] vLLM is up after ~$((i*10))s"; HEALTH_OK=1; break
  fi
  sleep 10
done
if [ "$HEALTH_OK" -ne 1 ]; then
  echo "[run] ERROR: vLLM failed to become healthy within ~20m" >&2
  exit 1
fi

export LLM_BASE_URL="http://localhost:${PORT}/v1"
export OPENAI_API_KEY="${OPENAI_API_KEY:-not-needed}"

cd /app
echo "[run] 1/4 download MS-LaTTE"
python -m sft_pipeline.latte.download --out "$SOURCES"
echo "[run] 2/4 parse"
python -m sft_pipeline.latte.parse --in "$SOURCES" --out "$PARSED"
echo "[run] 3/4 localize"
python -m sft_pipeline.latte.localize --in "$PARSED" --out "$SEEDS"

echo "[run] 4/4 synthesize ($SAMPLE_LIMIT samples, timeout=${REQUEST_TIMEOUT}s)"
TODAY_ARG=()
[ -n "$TODAY" ] && TODAY_ARG=(--today "$TODAY")
python -m sft_pipeline.latte.synthesize \
  --in "$SEEDS" --out "$OUT" \
  --use-llm --model "$MODEL" \
  --limit "$SAMPLE_LIMIT" \
  --timeout "$REQUEST_TIMEOUT" \
  "${TODAY_ARG[@]}"

if [ -n "${S3_BUCKET:-}" ]; then
  echo "[run] uploading to s3://${S3_BUCKET}/${S3_PREFIX:-sft/daily}"
  python -m sft_pipeline.latte.upload --in "$OUT" --bucket "$S3_BUCKET" --prefix "${S3_PREFIX:-sft/daily}"
else
  echo "[run] S3_BUCKET 미설정 — 업로드 건너뜀. 산출물: $OUT (RunPod 볼륨에서 수동 회수)"
fi

echo "[run] done."
