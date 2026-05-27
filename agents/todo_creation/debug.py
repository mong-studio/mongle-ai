from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

Kind = Literal["generate", "commit"]


def _enabled() -> bool:
    return os.getenv("MONGLE_DEBUG_TODO", "1") not in {"0", "false", "False", ""}


def _log_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "local_storage"


_current_log_path: Path | None = None
_current_jsonl_path: Path | None = None


def _emit(line: str) -> None:
    print(line, file=sys.stderr, flush=True)
    if _current_log_path is None:
        return
    try:
        with _current_log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as err:
        print(f"[todo_creation] log file write failed: {err}", file=sys.stderr)


def _jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _jsonl(event: str, **payload: Any) -> None:
    if _current_jsonl_path is None:
        return
    entry = {"ts": datetime.now().isoformat(), "event": event, **payload}
    try:
        with _current_jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=_jsonable) + "\n")
    except OSError as err:
        print(f"[todo_creation] jsonl write failed: {err}", file=sys.stderr)


def _format(text: str) -> str:
    return text.replace("\n", "\n                   ")


def _safe(value: str, fallback: str = "anon") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", value)[:64]
    return cleaned or fallback


def log_start(input: Any, kind: Kind) -> None:
    global _current_log_path, _current_jsonl_path
    if not _enabled():
        _current_log_path = None
        _current_jsonl_path = None
        return

    log_dir = _log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        print(f"[todo_creation] log dir creation failed: {err}", file=sys.stderr)
        _current_log_path = None
        _current_jsonl_path = None
        return

    user_id = getattr(input, "user_id", "anon")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{ts}_{_safe(user_id)}_todo_{kind}"

    _current_log_path = log_dir / f"{prefix}.log"
    _current_jsonl_path = log_dir / f"{prefix}.jsonl"

    summary = (
        getattr(input, "prompt", None)
        or getattr(input, "message", None)
        or (
            f"todos={len(getattr(input, 'todos', []))} "
            f"events={len(getattr(input, 'calendar_events', []))}"
        )
    )

    _emit("")
    _emit("=" * 72)
    _emit(f"[todo_creation] start  kind={kind}  user={user_id}")
    _emit(f"  input         : {_format(str(summary))}")
    _emit("=" * 72)
    _jsonl(
        "start",
        kind=kind,
        user_id=user_id,
        input=_jsonable(input),
    )


def _emit_task_list(key: str, tasks: list[Any]) -> None:
    _emit(f"  {key:18s}: {len(tasks)} items")
    for i, t in enumerate(tasks, 1):
        title = getattr(t, "title", "?")
        due = getattr(t, "due_date", "?")
        hint = getattr(t, "time_hint", None)
        hint_str = f" | {hint}" if hint else ""
        _emit(f"    [{i}] {title} | {due}{hint_str}")


def log_step(step: int, node: str, update: dict[str, Any] | None) -> None:
    if not _enabled():
        return
    _emit(f"[STEP {step}] {node}")
    if not update:
        _jsonl("step", step=step, node=node, update={})
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
            if key == "split_tasks" and isinstance(val, list):
                _emit_task_list(key, val)
            elif isinstance(val, list):
                _emit(f"  {key:18s}: {len(val)} items")
            else:
                _emit(f"  {key:18s}: {val}")
    error = update.get("error")
    if error is not None:
        _emit(f"  ERROR             : {type(error).__name__}: {error}")
    _jsonl("step", step=step, node=node, update=_jsonable(update))


def log_end(final: Any) -> None:
    global _current_log_path, _current_jsonl_path
    if not _enabled():
        return
    _emit("=" * 72)
    _emit("[todo_creation] done")
    _emit("")
    _jsonl("end", final=_jsonable(final) if final is not None else None)
    _current_log_path = None
    _current_jsonl_path = None
