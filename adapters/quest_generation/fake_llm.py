from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agents.quest_generation.exceptions import LLMFailedError
from agents.quest_generation.schemas import Character


@dataclass
class FakeLLM:
    """In-process fake of LLMPort. Mirrors the test fake; provided here for app wireup
    (e.g. development server without real OpenAI credentials)."""

    fail_times: int = 0
    text_for: Callable[[Character], str] | None = None
    calls: list[Character] = field(default_factory=list)

    async def generate_quest(self, *, character: Character) -> str:
        self.calls.append(character)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMFailedError("simulated LLM failure")
        if self.text_for is not None:
            return self.text_for(character)
        return f"{character.name}가 잠깐 한숨 돌리고 있어요."
