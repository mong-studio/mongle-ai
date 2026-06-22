"""이미지 생성 멀티-어댑터 파이프라인 (RunPod Serverless 워커용).

한 워커로 단독(어댑터 1개) 또는 합본을 지원한다. 요청의 adapter 이름으로 모드를
고르고, LoRA repo 는 환경변수로 주입한다. 모드는 첫 요청 시 lazy-load 한다(콜드
스타트에 SDXL 여러 벌을 한꺼번에 올리지 않기 위함):
  LORA_CHARACTER_REPO  — adapter="character" (사진→픽셀아트 스프라이트, ControlNet img2img)
  LORA_BG_REPO         — adapter="bg"        (텍스트→배경 장면, text2img + LCM)
  (둘 다 설정된 경우) adapter="feed"          (캐릭터 img2img+배경+합성+블렌딩 5단계)
"""
from __future__ import annotations

import os

# 어댑터 이름 → LoRA HF repo 를 지정하는 환경변수
_ADAPTER_ENV = {
    "character": "LORA_CHARACTER_REPO",
    "bg": "LORA_BG_REPO",
}


class MultiAdapterImagePipeline:
    """등록 가능한 어댑터를 lazy-load 하고 요청을 분기한다."""

    def __init__(self, *, adapters: dict[str, str]) -> None:
        self._adapters = adapters  # 이름 → LoRA repo
        self._modes: dict[str, object] = {}  # lazy 캐시

    def _available(self) -> set[str]:
        names = set(self._adapters)
        # feed 는 캐릭터+배경 LoRA 가 둘 다 있어야 가능(5단계 내부 합성)
        if "character" in self._adapters and "bg" in self._adapters:
            names.add("feed")
        return names

    def _load(self, adapter: str):
        if adapter == "character":
            from character_mode import CharacterMode

            return CharacterMode(lora_source=self._adapters["character"])
        if adapter == "bg":
            from bg_mode import BgMode

            return BgMode(lora_source=self._adapters["bg"])
        if adapter == "feed":
            from feed_mode import FeedMode

            return FeedMode(
                lora_character_source=self._adapters["character"],
                lora_bg_source=self._adapters["bg"],
            )
        raise ValueError(f"[ERROR] 알 수 없는 adapter: {adapter!r}")

    def generate(
        self,
        *,
        adapter: str,
        source_image_bytes: bytes | None = None,
        prompt: str | None = None,
        scene_prompt: str | None = None,
    ) -> bytes:
        if adapter not in self._available():
            raise ValueError(
                f"[ERROR] 알 수 없는 adapter: {adapter!r} "
                f"(이 엔드포인트가 서빙하는 어댑터: {sorted(self._available())})"
            )
        mode = self._modes.get(adapter)
        if mode is None:
            mode = self._modes.setdefault(adapter, self._load(adapter))
        return mode.generate(
            source_image_bytes=source_image_bytes,
            prompt=prompt,
            scene_prompt=scene_prompt,
        )


_pipeline: MultiAdapterImagePipeline | None = None


def get_pipeline() -> MultiAdapterImagePipeline:
    """워커 프로세스에서 파이프라인을 한 번만 구성(모드는 첫 요청 시 lazy-load)."""
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
