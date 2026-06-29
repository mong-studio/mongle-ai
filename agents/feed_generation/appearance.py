"""appearance_payload 폴백 — payload 가 없는 (v2 이전) 캐릭터용.

feed 워커는 캐릭터 정체성을 `appearance_payload`(구조화 dict)로만 받는다.
v2 이전에 생성된 캐릭터는 이 payload 가 없고 `visual`(외형 문자열)만 가진다.
그 캐릭터도 피드를 만들 수 있도록 visual 에서 payload 를 **결정적으로** 합성한다.

결정적(같은 visual → 항상 같은 payload)이라, 피드마다 캐릭터 외형이 일관된다.
신규 캐릭터는 워커가 만든 진짜 payload 를 쓰므로 이 경로를 타지 않는다.
"""
from __future__ import annotations

from typing import Any

# character_type 추출 시 떼어낼 앞쪽 수식어
_FILLERS = ("cute", "little", "baby", "small", "tiny", "soft", "pixel-art", "pixel art")
# main_colors 로 인식할 색 키워드
_COLORS = (
    "brown", "white", "black", "red", "pink", "blue", "green", "yellow",
    "gray", "grey", "orange", "purple", "cream", "tan", "golden", "gold",
    "silver", "beige",
)
# accessories 로 인식할 키워드
_ACCESSORIES = (
    "scarf", "hat", "coat", "armor", "glasses", "bow", "ribbon",
    "bottle", "tumbler", "cap", "crown", "backpack", "bag",
)
_BODY = ("fur", "belly", "body", "coat")
_FACE = ("eye", "eyes", "smile", "nose", "face")
_EARS = ("ear", "ears", "arm", "arms", "tail", "wing", "wings")


def _flatten(visual: Any) -> str:
    if isinstance(visual, (list, tuple)):
        return ", ".join(str(v).strip() for v in visual if v and str(v).strip())
    return str(visual or "").strip()


def _first_match(segments: list[str], keywords: tuple[str, ...]) -> str:
    for seg in segments:
        low = seg.lower()
        if any(k in low for k in keywords):
            return seg
    return ""


def _strip_fillers(head: str) -> str:
    words = head.split()
    while words and words[0].lower() in _FILLERS:
        words = words[1:]
    return " ".join(words) or head


def payload_from_visual(visual: Any) -> dict[str, Any]:
    """visual(문자열/리스트) → appearance_payload(dict).

    결정적이며 항상 non-empty 를 반환한다(빈 visual 도 안전 기본값으로 대체).
    """
    text = _flatten(visual) or "cute animal character"
    segments = [s.strip() for s in text.split(",") if s.strip()] or [text]
    head = segments[0]
    low = text.lower()
    colors = [c for c in _COLORS if c in low]
    rest = segments[1:] or segments
    return {
        "id": "runtime_visual",
        "character_type": _strip_fillers(head) or "character",
        "character_summary": text,
        "body": _first_match(segments, _BODY),
        "face": _first_match(segments, _FACE),
        "ears_arms": _first_match(segments, _EARS),
        "main_colors": colors,
        "accessories": [s for s in segments if any(a in s.lower() for a in _ACCESSORIES)],
        "must_preserve": rest[:5],
    }
