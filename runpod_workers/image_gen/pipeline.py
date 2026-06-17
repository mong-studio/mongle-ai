"""이미지 생성 멀티-어댑터 파이프라인 (RunPod Serverless 워커용).

한 워커로 단독(어댑터 1개) 또는 합본(character+bg)을 모두 지원한다.
요청의 adapter 이름으로 모드를 고르고, LoRA repo 는 환경변수로 주입한다.
설정된 어댑터만 등록한다(단독 배포는 1개, 합본은 2개):
  LORA_CHARACTER_REPO  — adapter="character" (사진→픽셀아트 스프라이트, ControlNet img2img)
  LORA_BG_REPO         — adapter="bg"        (텍스트→배경 장면, text2img + LCM)

각 모드는 자체 SDXL 파이프라인을 로드한다(VRAM 공유 없음). 합본 배포 시 SDXL 가
2벌 상주하므로 VRAM 여유가 필요하다 — from_pipe 공유는 후속 최적화.
"""
from __future__ import annotations

import os

# 어댑터 이름 → LoRA HF repo 를 지정하는 환경변수
_ADAPTER_ENV = {
    "character": "LORA_CHARACTER_REPO",
    "bg": "LORA_BG_REPO",
}


class MultiAdapterImagePipeline:
    """등록된 어댑터별 이미지 생성 모드를 보유하고 요청을 분기한다."""

    def __init__(self, *, adapters: dict[str, str]) -> None:
        # 무거운 diffusers 모드는 등록된 어댑터에 한해 지연 import 후 로드한다.
        self._modes: dict[str, object] = {}
        if "character" in adapters:
            from character_mode import CharacterMode

            self._modes["character"] = CharacterMode(lora_source=adapters["character"])
        if "bg" in adapters:
            from bg_mode import BgMode

            self._modes["bg"] = BgMode(lora_source=adapters["bg"])

    def generate(
        self,
        *,
        adapter: str,
        source_image_bytes: bytes | None = None,
        prompt: str | None = None,
    ) -> bytes:
        mode = self._modes.get(adapter)
        if mode is None:
            raise ValueError(
                f"[ERROR] 알 수 없는 adapter: {adapter!r} "
                f"(이 엔드포인트가 서빙하는 어댑터: {sorted(self._modes)})"
            )
        return mode.generate(source_image_bytes=source_image_bytes, prompt=prompt)


_pipeline: MultiAdapterImagePipeline | None = None


def get_pipeline() -> MultiAdapterImagePipeline:
    """워커 프로세스에서 파이프라인을 한 번만 로드(지연).

    환경변수가 설정된 어댑터만 등록한다(단독 엔드포인트는 1개, 합본은 2개).
    """
    global _pipeline
    if _pipeline is None:
        adapters = {
            name: repo
            for name, env_key in _ADAPTER_ENV.items()
            if (repo := os.environ.get(env_key, "").strip())
        }
        if not adapters:
            raise RuntimeError(
                f"[ERROR] LoRA repo 환경변수가 최소 1개 필요합니다: "
                f"{', '.join(_ADAPTER_ENV.values())}"
            )
        _pipeline = MultiAdapterImagePipeline(adapters=adapters)
    return _pipeline
