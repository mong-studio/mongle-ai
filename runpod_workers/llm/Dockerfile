FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/runpod-volume/hf-cache

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline.py handler.py ./

# 런타임 필수 env:
#   LORA_REPO_ID — LoRA HF repo ID
#     플래너: bigmooon/qwen2.5-7b-mongle-planner-ko-lora
#     빌리지: deeps1eep/qwen2.5-7b-mongle-village
#   HF_TOKEN     — private repo 접근 시 필요
CMD ["python", "-u", "handler.py"]
