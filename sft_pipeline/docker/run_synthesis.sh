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
CONCURRENCY="${CONCURRENCY:-16}"               # LLM 동시요청 수(vLLM 배치 활용). 순차=1
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
  if python3 -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:${PORT}/health',timeout=2)" >/dev/null 2>&1; then
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
python3 -m sft_pipeline.latte.download --out "$SOURCES"
echo "[run] 2/4 parse"
python3 -m sft_pipeline.latte.parse --in "$SOURCES" --out "$PARSED"
echo "[run] 3/4 localize"
python3 -m sft_pipeline.latte.localize --in "$PARSED" --out "$SEEDS"

echo "[run] 4/4 synthesize ($SAMPLE_LIMIT samples, timeout=${REQUEST_TIMEOUT}s)"
TODAY_ARG=()
[ -n "$TODAY" ] && TODAY_ARG=(--today "$TODAY")
python3 -m sft_pipeline.latte.synthesize \
  --in "$SEEDS" --out "$OUT" \
  --use-llm --model "$MODEL" \
  --limit "$SAMPLE_LIMIT" \
  --timeout "$REQUEST_TIMEOUT" \
  --concurrency "$CONCURRENCY" \
  "${TODAY_ARG[@]}"

if [ -n "${S3_BUCKET:-}" ]; then
  echo "[run] uploading to s3://${S3_BUCKET}/${S3_PREFIX:-sft/daily}"
  # 업로드가 실패해도 작업 전체를 멈추지 않는다. 권한이나 네트워크 오류로 스크립트가 죽으면
  # RunPod 가 컨테이너를 재시작해 합성을 처음부터 다시 돌리고, 같은 키를 덮어써 결과물을 잃게 된다.
  if python3 -m sft_pipeline.latte.upload --in "$OUT" --bucket "$S3_BUCKET" --prefix "${S3_PREFIX:-sft/daily}"; then
    echo "[run] upload OK"
  else
    echo "[run] WARNING: S3 업로드에 실패했습니다 — 결과물은 $OUT 에 그대로 있습니다. 권한·버킷을 확인한 뒤 컨테이너에 exec 로 접속해 다시 올리세요." >&2
  fi
else
  echo "[run] S3_BUCKET 미설정 — 업로드 건너뜀. 산출물: $OUT (RunPod 볼륨에서 수동 회수)"
fi

# 스크립트가 정상 종료하면 RunPod 가 컨테이너를 재시작해 합성을 처음부터 다시 돌리고,
# 같은 S3 키를 덮어쓴다(합성 결과는 매번 조금씩 달라진다). 이를 막으려고 작업이 끝나면
# 일부러 대기 상태로 둔다. vLLM 도 계속 떠 있어 exec 로 접속해 exam-synth 같은 후속 작업을
# 바로 이어서 돌릴 수 있다. 종료하려면 Pod 를 직접 STOP 한다.
echo "[run] done — 작업을 마쳤습니다. 재시작 루프를 막기 위해 컨테이너를 종료하지 않고 대기합니다."
echo "[run] 후속 작업은 exec 로 접속해 이어서 돌리고, 끝나면 Pod 를 직접 STOP 하세요."
sleep infinity
