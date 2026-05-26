from __future__ import annotations

import random

from agents.quest_generation.schemas import Character


class CharacterPool:
    """Round-robin character pool with auto-reset on exhaustion.

    - `next()` returns a character and removes it from the current round (C3).
    - When the round is exhausted, the pool is refilled with a fresh shuffle
      of the full character set (C4).
    - `seed=None` → non-deterministic (production default).
    - `seed=int`  → deterministic order (used in tests).
    """

    def __init__(self, characters: list[Character], *, seed: int | None = None) -> None:
        if not characters:
            raise ValueError("characters must be non-empty")
        self._all: tuple[Character, ...] = tuple(characters)
        self._rng = random.Random(seed)
        self._pool: list[Character] = []
        self._refill()

    def _refill(self) -> None:
        self._pool = list(self._all)
        self._rng.shuffle(self._pool)

    def next(self) -> Character:
        if not self._pool:
            self._refill()
        return self._pool.pop()
