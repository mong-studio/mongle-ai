from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

Kind = Literal["generate", "commit"]


def _enabled() -> bool:
    return os.getenv("MONGLE_DEBUG_TODO", "1") not in {"0", "false", "False", ""}


def _log_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "local_storage"


_current_log_path: Path | None = None


def _emit(line: str) -> None:
    print(line, file=sys.stderr, flush=True)
    if _current_log_path is None:
        return
    try:
        with _current_log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as err:
        print(f"[todo_creation] log file write failed: {err}", file=sys.stderr)


def _format(text: str) -> str:
    return text.replace("\n", "\n                   ")


def log_start(input: Any, kind: Kind) -> None:
    global _current_log_path
    if not _enabled():
        _current_log_path = None
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    user_id = getattr(input, "user_id", "anon")
    safe_user = re.sub(r"[^A-Za-z0-9_-]", "_", user_id)[:32] or "anon"
    log_dir = _log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        _current_log_path = log_dir / f"{ts}_{safe_user}_todo_{kind}.log"
    except OSError as err:
        print(f"[todo_creation] log dir creation failed: {err}", file=sys.stderr)
        _current_log_path = None

    _emit("")
    _emit("=" * 72)
    _emit(f"[todo_creation] start  kind={kind}  user={user_id}")
    summary = getattr(input, "prompt", None) or (
        f"todos={len(getattr(input, 'todos', []))} "
        f"events={len(getattr(input, 'calendar_events', []))}"
    )
    _emit(f"  input         : {_format(str(summary))}")
    _emit("=" * 72)


def log_step(step: int, node: str, update: dict[str, Any] | None) -> None:
    if not _enabled():
        return
    _emit(f"[STEP {step}] {node}")
    if not update:
        return
    for key in (
        "split_tasks",
        "result",
        "re_routed_todos",
        "re_routed_events",
        "idempotent_hit",
        "todo_ids",
        "event_ids",
        "quest_triggered",
    ):
        if key in update:
            val = update[key]
            if isinstance(val, list):
                _emit(f"  {key:14s}: {len(val)} items")
            else:
                _emit(f"  {key:14s}: {val}")
    error = update.get("error")
    if error is not None:
        _emit(f"  ERROR         : {type(error).__name__}: {error}")


def log_end(final: Any) -> None:
    global _current_log_path
    if not _enabled():
        return
    _emit("=" * 72)
    _emit("[todo_creation] done")
    _emit("")
    _current_log_path = None
