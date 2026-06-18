from __future__ import annotations

import logging
import time
from typing import Any

from agents.character_creation.state import CharacterGraphState

log = logging.getLogger(__name__)


async def translate_appearance_node(
    state: CharacterGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    """한국어 appearance 를 이미지용 영어 visual 태그로 번역해 llm_result 를 갱신한다.

    SDXL 텍스트 인코더(CLIP)가 영어 전용이라 한국어 외형 묘사는 이미지에 반영되지
    않는다. Qwen base 로 영어 태그로 바꿔 이미지 prompt 충실도를 확보한다.
    번역 실패 시 원본(한국어)을 유지한다 — 캐릭터 생성을 막지 않는다(이미지 품질만 저하).
    """
    ports = config["configurable"]["ports"]
    llm_result = state.get("llm_result")
    assert llm_result is not None
    start = time.perf_counter()
    try:
        english = (
            await ports.translator.translate_appearance(llm_result.appearance)
        ).strip()
    except Exception:
        log.exception("appearance 번역 실패 — 한국어 원본 유지")
        english = ""
    update: dict[str, Any] = (
        {"llm_result": llm_result.model_copy(update={"appearance": english})}
        if english
        else {}
    )
    update["translate_appearance_seconds"] = round(time.perf_counter() - start, 3)
    return update
