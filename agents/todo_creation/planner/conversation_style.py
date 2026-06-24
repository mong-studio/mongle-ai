from __future__ import annotations

import re

_MONGLE_RE = re.compile(r"\s*몽글[.!?~]*")


def render_chief_voice(text: str, *, question: bool = False) -> str:
    """사용자 노출 문장을 해요체 기반 말투와 '몽글' 1회로 정리한다."""

    cleaned = _MONGLE_RE.sub("", str(text or "")).strip()
    if not cleaned:
        cleaned = "함께 정리해볼게요"
    cleaned = cleaned.rstrip(" ,.!?~")
    ending = "?" if question else "."
    return f"{cleaned}, 몽글{ending}"
