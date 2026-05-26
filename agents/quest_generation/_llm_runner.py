from __future__ import annotations

from agents.quest_generation.exceptions import LLMFailedError
from agents.quest_generation.protocols import LLMPort
from agents.quest_generation.schemas import Character


class LLMRunner:
    """Calls LLMPort with bounded retry. Re-raises the last LLMFailedError on exhaustion."""

    def __init__(self, llm: LLMPort, *, max_retries: int = 2) -> None:
        self._llm = llm
        self._max_retries = max_retries

    async def generate(self, *, character: Character) -> str:
        last_err: LLMFailedError | None = None
        for _ in range(self._max_retries + 1):
            try:
                return await self._llm.generate_quest(character=character)
            except LLMFailedError as err:
                last_err = err
                continue
        assert last_err is not None
        raise last_err
