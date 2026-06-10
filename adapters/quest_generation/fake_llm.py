from __future__ import annotations

from dataclasses import dataclass

from agents.quest_generation.schemas import Character


@dataclass
class FakeLLM:
    async def generate_quest(self, *, character: Character) -> str:
        return "fake quest"
