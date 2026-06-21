# RunPod 올인원 이미지 — 한 컨테이너가 vLLM(Qwen 서빙) + 합성 파이프라인 + S3 업로드를 모두 수행.
# 베이스에 vLLM·CUDA·OpenAI 호환 서버가 포함되어 있다. 모델 가중치(예: Qwen2.5-14B ~28GB)는
# 이미지에 굽지 않고 런타임에 HuggingFace 에서 받는다(공개 모델, 토큰 불필요).
#
# 빌드(레포 루트를 컨텍스트로):
#   docker build -f sft_pipeline/docker/Dockerfile -t sft-synthesis .
# Pin to a specific release — bump tag intentionally when upgrading vLLM
FROM vllm/vllm-openai:v0.6.3

WORKDIR /app

# 파이프라인 런타임 의존성(vLLM 은 베이스에 포함). 다운로드/합성/검증/업로드용.
RUN pip install --no-cache-dir \
    "pydantic>=2.6,<3" \
    "openai>=1.50" \
    "requests>=2.31" \
    "boto3>=1.34" \
    "python-dotenv>=1.0"

# 패키지 임포트(sft_pipeline.*) 를 위해 레포 루트(/app) 아래에 코드 배치.
# .dockerignore 가 data/ 와 .env 를 제외하므로 대용량/시크릿은 들어오지 않는다.
COPY sft_pipeline /app/sft_pipeline

RUN chmod +x /app/sft_pipeline/docker/run_synthesis.sh

ENV PYTHONPATH=/app
# 베이스 이미지의 기본 ENTRYPOINT(API 서버)를 우리 오케스트레이션 스크립트로 교체.
ENTRYPOINT ["/app/sft_pipeline/docker/run_synthesis.sh"]
