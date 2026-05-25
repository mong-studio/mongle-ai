from __future__ import annotations

import hashlib
import logging
import time
from contextvars import ContextVar
from typing import Any, ClassVar
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

pipeline_id_var: ContextVar[str | None] = ContextVar("pipeline_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

PREVIEW_LIMIT = 2000


class BaseTraceCallback(BaseCallbackHandler):
    """LangGraph 노드/LLM 라이프사이클을 stdout JSON으로 추적하는 베이스.

    각 agent는 본 클래스를 상속하여 다음을 오버라이드한다:
    - REDACT_KEYS: 입력 dict에서 마스킹할 agent 특화 필드명 집합
    - LOGGER_NAME: 로거 이름 (agent 별로 분리)
    - domain_meta(): 모든 로그 페이로드에 자동 주입될 도메인 메타 필드

    user_id는 base에서 항상 마스킹된다 (_BASE_REDACT).
    """

    REDACT_KEYS: ClassVar[set[str]] = set()
    LOGGER_NAME: ClassVar[str] = "mongle.trace"
    _BASE_REDACT: ClassVar[set[str]] = {"user_id"}

    def __init__(self) -> None:
        self._started: dict[UUID, float] = {}
        self.log = logging.getLogger(self.LOGGER_NAME)

    # ---- 도메인 hook ----

    def domain_meta(self) -> dict[str, Any]:
        return {}

    # ---- 노드 (chain) ----

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        node = self._node_name(serialized, kwargs)
        if node is None:
            return
        self._started[run_id] = time.perf_counter()
        self.log.info(
            "node.start",
            extra={
                **self._base(),
                "node": node,
                "run_id": str(run_id),
                "inputs_preview": self._redact_preview(inputs),
            },
        )

    def on_chain_end(
        self,
        outputs: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        if run_id not in self._started:
            return
        self.log.info(
            "node.end",
            extra={
                **self._base(),
                "node": kwargs.get("name") or "<unknown>",
                "run_id": str(run_id),
                "duration_ms": self._elapsed(run_id),
                "ok": True,
                "outputs_preview": _preview(outputs),
            },
        )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        if run_id not in self._started:
            return
        self.log.exception(
            "node.error",
            extra={
                **self._base(),
                "node": kwargs.get("name") or "<unknown>",
                "run_id": str(run_id),
                "duration_ms": self._elapsed(run_id),
                "ok": False,
                "error_type": type(error).__name__,
            },
        )

    # ---- LLM ----

    def on_llm_start(
        self,
        serialized: dict[str, Any] | None,
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._started[run_id] = time.perf_counter()
        self.log.info(
            "llm.start",
            extra={
                **self._base(),
                "model": (serialized or {}).get("name") or (serialized or {}).get("id"),
                "run_id": str(run_id),
                "prompt_count": len(prompts),
                "prompt_preview": "<redacted>",
            },
        )

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        if run_id not in self._started:
            return
        self.log.info(
            "llm.end",
            extra={
                **self._base(),
                "run_id": str(run_id),
                "duration_ms": self._elapsed(run_id),
                "ok": True,
                **_extract_usage(response),
            },
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        if run_id not in self._started:
            return
        self.log.exception(
            "llm.error",
            extra={
                **self._base(),
                "run_id": str(run_id),
                "duration_ms": self._elapsed(run_id),
                "ok": False,
                "error_type": type(error).__name__,
            },
        )

    # ---- helpers ----

    def _base(self) -> dict[str, Any]:
        return {
            "pipeline_id": pipeline_id_var.get(),
            "session_id": session_id_var.get(),
            "user_hash": _hash(user_id_var.get()),
            **self.domain_meta(),
        }

    def _elapsed(self, run_id: UUID) -> float:
        started = self._started.pop(run_id, None)
        if started is None:
            return 0.0
        return round((time.perf_counter() - started) * 1000, 2)

    def _node_name(
        self,
        serialized: dict[str, Any] | None,
        kwargs: dict[str, Any],
    ) -> str | None:
        return kwargs.get("name") or (serialized or {}).get("name")

    def _redact_preview(self, inputs: Any) -> str:
        if isinstance(inputs, dict):
            redact = self._BASE_REDACT | self.REDACT_KEYS
            redacted = {
                key: ("<redacted>" if key in redact else value)
                for key, value in inputs.items()
            }
            return _preview(redacted)
        return _preview(inputs)


def _preview(value: Any) -> str:
    text = repr(value)
    if len(text) <= PREVIEW_LIMIT:
        return text
    return text[:PREVIEW_LIMIT] + "...<truncated>"


def _hash(user_id: str | None) -> str | None:
    if user_id is None:
        return None
    return hashlib.sha256(user_id.encode()).hexdigest()[:12]


def _extract_usage(response: Any) -> dict[str, Any]:
    try:
        llm_output = getattr(response, "llm_output", None) or {}
        usage = llm_output.get("token_usage", {}) if isinstance(llm_output, dict) else {}
        return {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
    except Exception:
        return {}
