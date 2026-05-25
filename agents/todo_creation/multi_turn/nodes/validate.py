from __future__ import annotations

import re
from typing import Any

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.schemas import MultiTurnInput

HANGUL_RATIO_MIN = 0.3

_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def _hangul_ratio(text: str) -> float:
    stripped = re.sub(r"\s", "", text)
    if not stripped:
        return 0.0
    return len(_HANGUL_RE.findall(stripped)) / len(stripped)


def check(input: MultiTurnInput) -> None:
    if len(input.message) > 600:
        raise ValidationError(code="M1", message="message exceeds 600 chars")
    if not input.message.strip():
        raise ValidationError(code="M2", message="message is empty or whitespace")
    if _hangul_ratio(input.message) < HANGUL_RATIO_MIN:
        raise ValidationError(code="M3", message="message must be mostly Korean")


async def validate_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    check(state["input"])
    return {}
