"""multi 모드 입력 검증 노드.

C2 — message 공백 포함 ≤600자, 한국어 음절 비율 ≥0.5 (한글 U+AC00–U+D7A3 기준,
공백·숫자는 분모 제외). 빈/공백 거부.

통과 시 user message 를 `state["history"]` 끝에 append. 이후 graph 가 `add_edge`
로 planner 노드 진입.
"""

from __future__ import annotations

from typing import Any

from agents.todo_creation.exceptions import ValidationError


def _korean_syllable_ratio(text: str) -> float:
    """한글 음절(U+AC00–U+D7A3) 비율. 공백·숫자는 분모 제외."""
    chars = [c for c in text if not c.isspace() and not c.isdigit()]
    if not chars:
        return 0.0
    hangul = sum(1 for c in chars if 0xAC00 <= ord(c) <= 0xD7A3)
    return hangul / len(chars)


async def multi_validate_node(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    message = state.get("message", "")
    if not message or not message.strip():
        raise ValidationError(code="C2", message="multi_validate: empty message")
    if len(message) > 600:
        raise ValidationError(
            code="C2", message=f"multi_validate: length {len(message)} > 600"
        )
    if _korean_syllable_ratio(message) < 0.5:
        raise ValidationError(
            code="C2", message="multi_validate: korean syllable ratio < 0.5"
        )
    history = state.get("history", [])
    return {"history": history + [{"role": "user", "content": message}]}
