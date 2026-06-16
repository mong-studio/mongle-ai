from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_ROOT = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=8)
def load(name: str) -> str:
    """Load a prompt file by basename (without `.md`).

    Example: load("llm_persona_v1") -> contents of adapters/character_creation/prompts/llm_persona_v1.md
    """
    path = _PROMPTS_ROOT / f"{name}.md"
    return path.read_text(encoding="utf-8")
