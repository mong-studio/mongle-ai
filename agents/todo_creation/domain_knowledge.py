"""Domain knowledge helpers for TODO planner goals.

The UI tag is intentionally short, so domain wiki lookup must not depend on
`goal_tag` alone.  These helpers resolve a wiki from the structured goal
context and expose small, deterministic snippets that both adapters and planner
fallbacks can share.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

log = logging.getLogger(__name__)

_WIKI_DIR = Path(__file__).parent / "domain_wiki"
_INDEX_PATH = _WIKI_DIR / "index.json"
_EXAM_PARTS = ("필기", "실기")


@dataclass(frozen=True)
class DomainWiki:
    label: str
    file: str
    content: str


def load_wiki(goal_tag: str) -> str | None:
    """Return wiki content for a direct query, preserving the old public API."""

    wiki = match_wiki(goal_tag)
    return wiki.content if wiki else None


def match_wiki(query: str, *, required_part: str | None = None) -> DomainWiki | None:
    """Return a domain wiki whose indexed keyword directly matches `query`."""

    normalized = _normalize(query)
    if not normalized:
        return None
    required_part_norm = _normalize(required_part)
    for entry in _load_index():
        if required_part_norm and not _entry_has_part(entry, required_part_norm):
            continue
        for keyword in entry.get("keywords", []):
            keyword_norm = _normalize(keyword)
            if keyword_norm in normalized or normalized in keyword_norm:
                return _read_wiki_entry(entry, query)
    return None


def resolve_domain_wiki(parsed_goal: Mapping[str, Any]) -> DomainWiki | None:
    """Resolve the best wiki from goal text, tag, slots, and exam part.

    `goal_tag` is capped to six characters for persistence, so a generic tag
    like "정보처리기사" still needs `slots.exam_part="실기"` to reach the
    part-specific wiki.
    """

    slots = parsed_goal.get("slots")
    slots = slots if isinstance(slots, Mapping) else {}
    exam_part = _exam_part(slots.get("exam_part"))
    for query in _goal_queries(parsed_goal):
        wiki = match_wiki(query, required_part=exam_part)
        if wiki:
            return wiki
    return _match_part_specific_wiki(parsed_goal)


def recommended_task_titles_for_goal(
    parsed_goal: Mapping[str, Any], *, limit: int | None = None
) -> list[str]:
    """Return 20-char-or-shorter task names from the matched domain wiki."""

    wiki = resolve_domain_wiki(parsed_goal)
    if wiki is None:
        return []
    titles = _extract_recommended_task_titles(wiki.content)
    return titles[:limit] if limit is not None else titles


def _load_index() -> list[dict[str, Any]]:
    try:
        payload = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as err:
        log.warning("domain_wiki index load failed: %s", err)
        return []
    mappings = payload.get("mappings", [])
    return mappings if isinstance(mappings, list) else []


def _read_wiki_entry(entry: Mapping[str, Any], query: str) -> DomainWiki | None:
    filename = str(entry.get("file") or "")
    if not filename:
        return None
    wiki_path = _WIKI_DIR / filename
    try:
        content = wiki_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("domain_wiki file missing: %s", wiki_path)
        return None
    label = str(entry.get("label") or filename.rsplit(".", 1)[0])
    log.debug("domain_wiki matched '%s' -> %s", query, filename)
    return DomainWiki(label=label, file=filename, content=content)


def _goal_queries(parsed_goal: Mapping[str, Any]) -> list[str]:
    slots = parsed_goal.get("slots")
    slots = slots if isinstance(slots, Mapping) else {}
    exam_part = _exam_part(slots.get("exam_part"))
    base_values = [
        parsed_goal.get("goal_tag"),
        parsed_goal.get("goal_text"),
        slots.get("exam_name"),
        slots.get("exam"),
        slots.get("certificate"),
    ]

    queries: list[str] = []
    if exam_part:
        queries.extend(f"{value} {exam_part}" for value in base_values if value)
    queries.extend(str(value) for value in base_values if value)
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))


def _match_part_specific_wiki(parsed_goal: Mapping[str, Any]) -> DomainWiki | None:
    slots = parsed_goal.get("slots")
    slots = slots if isinstance(slots, Mapping) else {}
    exam_part = _exam_part(slots.get("exam_part"))
    if not exam_part:
        return None

    part_norm = _normalize(exam_part)
    context = _normalize(" ".join(_goal_context_values(parsed_goal, slots)))
    if not context:
        return None

    for entry in _load_index():
        if not _entry_has_part(entry, part_norm):
            continue
        labels = [entry.get("label"), *entry.get("keywords", [])]
        stems = {
            _normalize(label).replace(part_norm, "")
            for label in labels
            if _normalize(label).replace(part_norm, "")
        }
        if any(stem in context for stem in stems):
            return _read_wiki_entry(entry, f"{context}:{exam_part}")
    return None


def _goal_context_values(
    parsed_goal: Mapping[str, Any], slots: Mapping[str, Any]
) -> list[str]:
    values = [parsed_goal.get("goal_tag"), parsed_goal.get("goal_text")]
    values.extend(slots.values())
    return [str(value) for value in values if value not in (None, "", [], {})]


def _exam_part(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in _EXAM_PARTS else None


def _entry_has_part(entry: Mapping[str, Any], part_norm: str) -> bool:
    labels = [entry.get("label"), *entry.get("keywords", [])]
    return any(part_norm in _normalize(label) for label in labels)


def _normalize(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def _extract_recommended_task_titles(content: str) -> list[str]:
    titles: list[str] = []
    in_section = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if in_section:
                break
            in_section = "추천 태스크 이름" in line
            continue
        if not in_section:
            continue
        match = re.match(r"^-\s+(.+)$", line)
        if not match:
            continue
        title = re.sub(r"[*_`]", "", match.group(1)).strip()
        if title:
            titles.append(title[:20].rstrip())
    return list(dict.fromkeys(titles))
