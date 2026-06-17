# RunPod GPU 드라이버(CUDA 12.x)와 호환되는 torch(2.4.0+cu124) 사전설치 베이스.
# slim+미핀 torch 는 최신 cu 빌드를 끌어와 "NVIDIA driver too old" 로 런타임 사망한다.
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

# HF_HOME 은 런타임 네트워크 볼륨(/runpod-volume)과 겹치면 안 된다.
# 겹치면 빌드 시 구운 SDXL/ControlNet 가중치가 볼륨 마운트에 가려져(shadowed)
# 콜드스타트마다 베이스를 재다운로드(HF 429 throttling)하게 된다.
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

COPY pipeline.py handler.py character_mode.py bg_mode.py ./

# 런타임 env (설정된 어댑터만 등록 — 단독/합본 겸용):
#   LORA_CHARACTER_REPO — 캐릭터 픽셀아트 LoRA HF repo ID (adapter="character")
#   LORA_BG_REPO        — 배경 LoRA HF repo ID            (adapter="bg")
#   HF_TOKEN            — private repo 면 필요
CMD ["python", "-u", "handler.py"]
