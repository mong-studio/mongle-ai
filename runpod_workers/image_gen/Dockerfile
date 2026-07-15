# syntax=docker/dockerfile:1.7
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/hf-cache \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    MODEL_CACHE_MODE=auto \
    PRELOAD_MODELS=false \
    MASCOT_LORA_SOURCE=Hadimeeee/mongle-mascot-lora \
    CHAR_LORA_SOURCE=Hadimeeee/mongle-character-lora \
    LCM_LORA_SOURCE=latent-consistency/lcm-lora-sdxl

WORKDIR /app

COPY requirements-ml.txt /tmp/requirements-ml.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements-ml.txt

COPY model_refs.py bake.py /app/
RUN --mount=type=secret,id=HF_TOKEN \
    export HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" \
    && python bake.py

COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt

COPY handler.py /app/handler.py
COPY pipelines /app/pipelines

CMD ["python", "-u", "handler.py"]
