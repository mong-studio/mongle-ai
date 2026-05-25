from __future__ import annotations

from contextvars import ContextVar
from typing import Any, ClassVar

from agents._shared.observability.trace_base import BaseTraceCallback

chat_type: ContextVar[str | None] = ContextVar("chat_type", default=None)


class TodoTraceCallback(BaseTraceCallback):
    """TODO/플랜 파이프라인 전용 추적. base 라이프사이클에 TODO 특화 메타 주입.

    - REDACT_KEYS: 싱글턴 prompt / 멀티턴 message 마스킹 (user_id는 base에서 처리)
    - chat_type: 싱글턴/멀티턴 구분, 모든 로그 페이로드에 자동 주입
    """

    REDACT_KEYS: ClassVar[set[str]] = {"prompt", "message"}
    LOGGER_NAME: ClassVar[str] = "mongle.todo.trace"

    def domain_meta(self) -> dict[str, Any]:
        return {"chat_type": chat_type.get()}