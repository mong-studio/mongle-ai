"""시험명 별칭 → 표준코드 변환. 매칭 실패 시 None (추정 금지)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "exam_types.yaml"


def _norm(text: str) -> str:
    return text.lower().replace(" ", "").replace("_", "")


@lru_cache(maxsize=1)
def _alias_index() -> list[tuple[str, str]]:
    with open(_CONFIG, encoding="utf-8") as f:
        mapping = yaml.safe_load(f)
    pairs: list[tuple[str, str]] = []
    for canonical, aliases in mapping.items():
        pairs.append((_norm(canonical), canonical))
        for alias in aliases:
            pairs.append((_norm(alias), canonical))
    # 중복 제거 (canonical이 별칭 목록에도 있으면 중복 생성됨), 순서 유지
    pairs = list(dict.fromkeys(pairs))
    # 긴 별칭 먼저 매칭 (컴활1급 vs 컴활)
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def canonicalize_exam_type(raw: str | None) -> str | None:
    needle = _norm(raw or "")
    if not needle:
        return None
    for alias_norm, canonical in _alias_index():
        if alias_norm == needle:
            return canonical
    return None
