"""
goal_tag 기반으로 domain_wiki MD 파일을 로드하는 유틸리티.
벡터 DB 없이 키워드 매칭으로 RAG를 대체한다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_WIKI_DIR = Path(__file__).parent.parent.parent / "agents" / "todo_creation" / "domain_wiki"
_INDEX_PATH = _WIKI_DIR / "index.json"


def _load_index() -> list[dict]:
    try:
        return json.loads(_INDEX_PATH.read_text(encoding="utf-8")).get("mappings", [])
    except (FileNotFoundError, json.JSONDecodeError) as err:
        log.warning("domain_wiki index load failed: %s", err)
        return []


def load_wiki(goal_tag: str) -> str | None:
    """goal_tag와 키워드가 일치하는 도메인 위키 MD 내용을 반환한다. 없으면 None."""
    normalized = goal_tag.replace(" ", "").lower()
    for entry in _load_index():
        for kw in entry.get("keywords", []):
            if kw.replace(" ", "").lower() in normalized or normalized in kw.replace(" ", "").lower():
                wiki_path = _WIKI_DIR / entry["file"]
                try:
                    content = wiki_path.read_text(encoding="utf-8")
                    log.debug("domain_wiki matched '%s' → %s", goal_tag, entry["file"])
                    return content
                except FileNotFoundError:
                    log.warning("domain_wiki file missing: %s", wiki_path)
                    return None
    return None
