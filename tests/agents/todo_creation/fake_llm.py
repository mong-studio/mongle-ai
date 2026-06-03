from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.schemas import TaskCandidate


@dataclass
class FakeLLM:
    """Scripted LLM for tests.

    - `responses`: queue of `list[TaskCandidate]` returned on each successful call.
    - `fail_times`: raise `LLMFailedError` this many times before any response is returned.
    """

    responses: list[list[TaskCandidate]] = field(default_factory=list)
    fail_times: int = 0
    calls: int = 0

    async def split_tasks(
        self, *, prompt: str, today: date
    ) -> list[TaskCandidate]:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMFailedError("simulated LLM failure")
        return self.responses.pop(0)
