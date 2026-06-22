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

# bake(가중치 사전 다운로드)를 app 의존성(runpod SDK)보다 앞 레이어에 둔다.
# 이렇게 하면 runpod SDK 버전만 바꿀 때 bake 캐시가 유지되고 SDXL 수 GB 재다운로드가 생략된다.
COPY requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt

COPY bake.py ./
RUN python bake.py

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline.py handler.py character_mode.py bg_mode.py feed_mode.py ./

# 런타임 env (설정된 어댑터만 등록 — 단독/합본 겸용):
#   LORA_CHARACTER_REPO — 캐릭터 픽셀아트 LoRA HF repo ID (adapter="character")
#   LORA_BG_REPO        — 배경 LoRA HF repo ID            (adapter="bg")
#   (둘 다 설정 시) adapter="feed" 5단계 파이프라인 사용 가능 (feed_mode.py)
#   HF_TOKEN            — private repo 면 필요
CMD ["python", "-u", "handler.py"]
