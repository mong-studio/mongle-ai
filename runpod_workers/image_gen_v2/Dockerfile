FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/runpod-volume/huggingface \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    MODEL_CACHE_MODE=auto \
    PRELOAD_MODELS=false \
    MASCOT_LORA_SOURCE=Hadimeeee/mongle-mascot-lora \
    CHAR_LORA_SOURCE=Hadimeeee/mongle-character-lora \
    LCM_LORA_SOURCE=latent-consistency/lcm-lora-sdxl

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY handler.py /app/handler.py
COPY total /app/total

CMD ["python", "-u", "handler.py"]
