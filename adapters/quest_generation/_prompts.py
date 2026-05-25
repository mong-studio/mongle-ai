from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_ROOT = (
    Path(__file__).resolve().parents[2] / "src" / "prompts" / "quest_generation"
)


@lru_cache(maxsize=8)
def load(name: str) -> str:
    """Load a prompt file by basename (without `.md`).

    Example: load("quest_text_v1") → contents of src/prompts/quest_generation/quest_text_v1.md
    """
    path = _PROMPTS_ROOT / f"{name}.md"
    return path.read_text(encoding="utf-8")
