FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/hf-cache

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 베이스 모델(Qwen2.5-7B-Instruct) 빌드 시 미리 받아 콜드스타트 단축
COPY bake.py ./
RUN python bake.py

COPY pipeline.py handler.py ./

# 런타임 필수 env:
#   LORA_REPO_ID — LoRA HF repo ID
#     플래너: bigmooon/qwen2.5-7b-mongle-planner-ko-lora
#     빌리지: deeps1eep/qwen2.5-7b-mongle-village
#   HF_TOKEN     — private repo 접근 시 필요
CMD ["python", "-u", "handler.py"]
