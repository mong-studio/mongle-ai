from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agents.quest_generation.exceptions import LLMFailedError
from agents.quest_generation.schemas import Character


@dataclass
class FakeLLM:
    """Configurable fake implementing LLMPort.

    - `fail_times`: number of leading calls that raise LLMFailedError.
    - `text_for`: optional callable to compute text per character (default deterministic).
    - `calls`: list of Character objects received, in order.
    """

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
        return f"{character.name}의 혼잣말입니다."
