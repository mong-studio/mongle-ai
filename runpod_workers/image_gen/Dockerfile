FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/hf-cache

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 공개 베이스 모델(SDXL + ControlNet + rembg u2net)을 빌드 시 미리 받아 콜드스타트 단축
COPY bake.py ./
RUN python bake.py

COPY pipeline.py handler.py ./

# 런타임 필수 env:
#   LORA_REPO_ID — 픽셀아트 LoRA HF repo ID
#   HF_TOKEN     — private repo 면 필요
CMD ["python", "-u", "handler.py"]
