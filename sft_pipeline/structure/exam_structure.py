"""시험별 구조(과목/파트/영역) 로더 + 구체성 측정. 미등록 시험은 None (추정 금지)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "exam_structures.yaml"


def _norm(text: str) -> str:
    return text.lower().replace(" ", "")


@lru_cache(maxsize=1)
def load_exam_structures() -> dict[str, dict]:
    with open(_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def structure_for(exam_type: str) -> dict | None:
    return load_exam_structures().get(exam_type)


def concreteness_ratio(titles: list[str], exam_type: str) -> float:
    """구조 키워드(과목/파트명)를 포함한 title 비율(0.0~1.0).

    빈 목록·미등록 시험은 0.0 — 게이트에서 안전하게 reject 방향으로 동작한다.
    """
    structure = structure_for(exam_type)
    if not structure or not titles:
        return 0.0
    keywords = [_norm(str(k)) for k in structure.get("keywords", [])]
    hits = sum(1 for t in titles if any(k in _norm(t) for k in keywords))
    return hits / len(titles)
