from __future__ import annotations

from collections import defaultdict

from agents.character_creation.schemas import CharacterEntity


class InMemoryCharacterRepository:
    def __init__(self) -> None:
        self._by_user: dict[str, list[CharacterEntity]] = defaultdict(list)
        self._regen_today: dict[str, int] = defaultdict(int)

    async def increment(self, user_id: str) -> int:
        self._regen_today[user_id] += 1
        return self._regen_today[user_id]

    async def save(self, entity: CharacterEntity) -> None:
        self._by_user[entity.user_id].append(entity)
