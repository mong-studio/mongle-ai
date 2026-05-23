from __future__ import annotations

from agents.character_creation.schemas import CharacterEntity


class InMemoryRepo:
    """Implements CharacterRepositoryPort with dict storage.

    Lives inside Streamlit session_state. Resets when the Streamlit process restarts.
    """

    def __init__(self) -> None:
        self._characters: dict[str, list[CharacterEntity]] = {}
        self._today_regen: dict[str, int] = {}

    async def count_active(self, user_id: str) -> int:
        return len(self._characters.get(user_id, []))

    async def today_regen_count(self, user_id: str) -> int:
        return self._today_regen.get(user_id, 0)

    async def save(self, entity: CharacterEntity) -> None:
        self._characters.setdefault(entity.user_id, []).append(entity)

    async def increment(self, user_id: str) -> int:
        new_value = self._today_regen.get(user_id, 0) + 1
        self._today_regen[user_id] = new_value
        return new_value

    def list_characters(self, user_id: str) -> list[CharacterEntity]:
        return list(self._characters.get(user_id, []))
