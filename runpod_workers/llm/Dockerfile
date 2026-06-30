FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

# HF_HOME 은 네트워크 볼륨 마운트 경로(/runpod-volume)와 겹치면 안 된다.
# 겹칠 경우 빌드 시 구워 둔 모델이 런타임 볼륨 마운트에 가려져(shadowed),
# 콜드스타트마다 베이스 15GB 를 재다운로드(unauthenticated throttling)하게 된다.
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/hf-cache

# 베이스 모델 선택(build-arg). 기본은 character용 Qwen.
# planner 이미지는 반드시 LoRA 학습 베이스와 같은 모델로 빌드한다.
# 예: EXAONE 기반 LoRA 를 쓸 때만 아래처럼 override 한다.
#   docker build --build-arg LLM_BASE_MODEL=LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct \
#                --build-arg LLM_BASE_MODEL_REVISION= -t <planner-image> .
# ENV 로 구워 두면 bake(빌드)와 pipeline(런타임)이 같은 모델을 본다(불일치 방지).
ARG LLM_BASE_MODEL="Qwen/Qwen2.5-7B-Instruct"
ARG LLM_BASE_MODEL_REVISION="a09a35458c702b33eeacc393d103063234e8bc28"
ENV LLM_BASE_MODEL=${LLM_BASE_MODEL} \
    LLM_BASE_MODEL_REVISION=${LLM_BASE_MODEL_REVISION}

WORKDIR /app

# 베이스 모델을 먼저 구워 둔다.
# huggingface_hub 만 가볍게 깔아 굽고, 무거운 requirements 설치는 뒤로 미룬다.
# (베이스 이미지엔 huggingface_hub 가 없으므로 반드시 먼저 설치해야 함)
# 이렇게 하면 requirements.txt 변경이 이 15GB 다운로드 레이어 캐시를 무효화하지 않아,
# 의존성만 바뀔 때 재다운로드→HF 429 로 빌드가 깨지던 문제를 막는다.
RUN pip install --no-cache-dir "huggingface-hub>=0.24"
COPY bake.py ./
RUN python bake.py

COPY requirements.txt ./
# vllm 이 끌어오는 torch(cu124) 와 ABI 가 어긋나는, 베이스 이미지 사전설치
# flashinfer 를 제거한다. 없으면 vllm 은 PyTorch-native 샘플러로 폴백한다.
# (미제거 시 워커 부팅에서 undefined symbol 로 사망 → completed:0 churn)
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y flashinfer flashinfer-python 2>/dev/null || true

COPY pipeline.py handler.py ./

# 런타임 필수 env:
#   LORA_REPO_ID — LoRA HF repo ID
#     플래너: bigmooon/qwen2.5-7b-mongle-planner-ko-lora
#     빌리지: deeps1eep/qwen2.5-7b-mongle-village
#   HF_TOKEN     — private repo 접근 시 필요
CMD ["python", "-u", "handler.py"]
