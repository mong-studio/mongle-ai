from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
    VLMResult,
)


def _enabled() -> bool:
    return os.getenv("MONGLE_DEBUG_CHARACTER", "1") not in {"0", "false", "False", ""}


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
        print(f"[character_creation] log file write failed: {err}", file=sys.stderr)


def _format(text: str) -> str:
    return text.replace("\n", "\n                   ")


def log_start(input: CharacterCreationInput) -> None:
    global _current_log_path
    if not _enabled():
        _current_log_path = None
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", input.name)[:32] or "unnamed"
    safe_user = re.sub(r"[^A-Za-z0-9_-]", "_", input.user_id)[:32] or "anon"
    log_dir = _log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        _current_log_path = log_dir / f"{ts}_{safe_user}_{safe_name}.log"
    except OSError as err:
        print(f"[character_creation] log dir creation failed: {err}", file=sys.stderr)
        _current_log_path = None

    _emit("")
    _emit("=" * 72)
    _emit(f"[character_creation] start  user={input.user_id}  name={input.name}")
    _emit(f"  persona       : {_format(input.persona)}")
    _emit(f"  keywords      : {[k.value for k in input.personality_keywords]}")
    _emit(
        f"  source_image  : "
        f"{input.source_image.filename if input.source_image else None}"
    )
    _emit("=" * 72)


def log_step(step: int, node: str, update: dict[str, Any] | None) -> None:
    if not _enabled():
        return

    _emit(f"[STEP {step}] {node}")

    if not update:
        return

    llm_result = update.get("llm_result")
    if isinstance(llm_result, LLMPersonaResult):
        _emit("  --- LLM persona ---")
        _emit(f"  personality    : {_format(llm_result.personality)}")
        _emit(f"  speech_style   : {_format(llm_result.speech_style)}")
        _emit(f"  background     : {_format(llm_result.background)}")

    vlm_result = update.get("vlm_result")
    if isinstance(vlm_result, VLMResult):
        _emit("  --- VLM appearance ---")
        _emit(f"  appearance     : {_format(vlm_result.appearance_description)}")
    elif "vlm_result" in update and vlm_result is None:
        _emit("  vlm_result     : None (VLM 실패 후 degrade)")

    source_url = update.get("source_url")
    if source_url:
        _emit(f"  source_url     : {source_url}")

    generated_url = update.get("generated_url")
    if generated_url:
        _emit(f"  generated_url  : {generated_url}")

    image_bytes = update.get("image_bytes")
    if image_bytes is not None:
        _emit(f"  image_bytes    : {len(image_bytes)} bytes")

    entity = update.get("entity")
    if isinstance(entity, CharacterEntity):
        _emit("  --- Final entity ---")
        _emit(f"  character_id   : {entity.character_id}")
        _emit(f"  image_url      : {entity.image_url}")

    error = update.get("error")
    if error is not None:
        _emit(f"  ERROR          : {type(error).__name__}: {error}")


def log_end(final: Any) -> None:
    global _current_log_path
    if not _enabled():
        return
    _emit("=" * 72)
    _emit("[character_creation] done")
    _emit("")
    _current_log_path = None
