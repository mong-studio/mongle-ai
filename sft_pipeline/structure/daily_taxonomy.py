"""plan_kind·domain 별칭 → 표준코드. 매칭 실패 시 None (추정 금지)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "daily_taxonomy.yaml"


def _norm(text: str) -> str:
    return text.lower().replace(" ", "").replace("_", "")


@lru_cache(maxsize=1)
def _config() -> dict:
    with open(_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _index(section: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for canonical, aliases in _config()[section].items():
        pairs.append((_norm(canonical), canonical))
        for alias in aliases:
            pairs.append((_norm(alias), canonical))
    pairs = list(dict.fromkeys(pairs))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


@lru_cache(maxsize=1)
def _plan_kind_index() -> list[tuple[str, str]]:
    return _index("plan_kinds")


@lru_cache(maxsize=1)
def _domain_index() -> list[tuple[str, str]]:
    return _index("domains")


def _lookup(index: list[tuple[str, str]], raw: str | None) -> str | None:
    needle = _norm(raw or "")
    if not needle:
        return None
    for alias_norm, canonical in index:
        if alias_norm == needle:
            return canonical
    return None


def canonicalize_plan_kind(raw: str | None) -> str | None:
    return _lookup(_plan_kind_index(), raw)


def canonicalize_domain(raw: str | None) -> str | None:
    return _lookup(_domain_index(), raw)


VALID_PLAN_KINDS = {"exam", "routine", "vague_goal", "lifestyle"}
VALID_DOMAINS = {"운동", "학습", "휴식", "관계", "정리"}
