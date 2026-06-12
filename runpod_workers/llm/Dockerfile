FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

# HF_HOME 은 네트워크 볼륨 마운트 경로(/runpod-volume)와 겹치면 안 된다.
# 겹칠 경우 빌드 시 구워 둔 모델이 런타임 볼륨 마운트에 가려져(shadowed),
# 콜드스타트마다 베이스 15GB 를 재다운로드(unauthenticated throttling)하게 된다.
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/hf-cache

WORKDIR /app

COPY requirements.txt ./
# vllm 이 끌어오는 torch(cu124) 와 ABI 가 어긋나는, 베이스 이미지 사전설치
# flashinfer 를 제거한다. 없으면 vllm 은 PyTorch-native 샘플러로 폴백한다.
# (미제거 시 워커 부팅에서 undefined symbol 로 사망 → completed:0 churn)
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y flashinfer flashinfer-python 2>/dev/null || true

# 공개 베이스 모델(Qwen2.5-7B-Instruct)을 빌드 시 이미지에 미리 구워
# 콜드스타트마다 재다운로드되는 것을 방지한다. (LoRA 는 런타임에 HF_TOKEN 으로)
COPY bake.py ./
RUN python bake.py

COPY pipeline.py handler.py ./

# 런타임 필수 env:
#   LORA_REPO_ID — LoRA HF repo ID
#     플래너: bigmooon/qwen2.5-7b-mongle-planner-ko-lora
#     빌리지: deeps1eep/qwen2.5-7b-mongle-village
#   HF_TOKEN     — private repo 접근 시 필요
CMD ["python", "-u", "handler.py"]
