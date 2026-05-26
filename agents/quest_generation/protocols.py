from __future__ import annotations

from typing import Protocol

from agents.quest_generation.schemas import Character


class LLMPort(Protocol):
    async def generate_quest(self, *, character: Character) -> str: ...
