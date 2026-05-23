from __future__ import annotations

from collections import defaultdict

from agents.character_creation.schemas import CharacterEntity


class InMemoryCharacterRepository:
    def __init__(self) -> None:
        self._by_user: dict[str, list[CharacterEntity]] = defaultdict(list)
        self._regen_today: dict[str, int] = defaultdict(int)

    async def count_active(self, user_id: str) -> int:
        return len(self._by_user[user_id])

    async def today_regen_count(self, user_id: str) -> int:
        return self._regen_today[user_id]

    def set_regen_count(self, user_id: str, value: int) -> None:
        self._regen_today[user_id] = value

    async def save(self, entity: CharacterEntity) -> None:
        self._by_user[entity.user_id].append(entity)
