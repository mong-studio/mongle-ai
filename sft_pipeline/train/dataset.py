"""학습용 데이터 로딩/필터.

토큰화·마스킹은 unsloth/trl 에 위임하고, 여기서는 학습 직전 마지막 위생 검사만 한다:
- 마지막 메시지가 assistant 이고 내용이 비어있지 않은 샘플만 통과(label 0 개 샘플 방지,
  sft-coherence 원칙 3 — NaN loss 예방).
mix→split 단계에서 이미 검증된 데이터를 받지만, 학습 진입점에서 한 번 더 막는다(fail-safe).
"""

from __future__ import annotations

import json
from pathlib import Path


def is_trainable(sample: dict) -> bool:
    """마지막 턴이 비어있지 않은 assistant 응답인지(학습 대상 토큰 존재)."""
    messages = sample.get("messages")
    if not messages:
        return False
    last = messages[-1]
    if last.get("role") != "assistant":
        return False
    return bool((last.get("content") or "").strip())


def load_messages(path: str | Path) -> list[dict]:
    """jsonl 을 읽어 학습 가능한 샘플만 반환. 빈 줄·비학습 샘플은 건너뛴다."""
    path = Path(path)
    raw = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    good = [s for s in raw if is_trainable(s)]
    dropped = len(raw) - len(good)
    if dropped:
        print(f"[train] {path.name}: {dropped}건 제외(빈 assistant/형식 오류), {len(good)}건 학습")
    return good
