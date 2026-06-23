from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import SplitResult, TaskCandidate


@dataclass
class FakeLLM:
    """Scripted LLM for tests.

    - `responses`: queue of `list[TaskCandidate]` consumed by call index independently of `intents`.
    - `intents`: queue of intent strings consumed by call index independently of `responses`.
      When `intents` is exhausted, `"plan"` is substituted for remaining calls.
    - `fail_times`: raise `LLMFailedError` this many times before any response is returned.
    - `output_fail_times`: raise `LLMOutputError` this many times (반복·무의미 입력으로
      재시도 후에도 파싱 불가한 상황을 흉내낸다). `fail_times` 소진 후에 적용된다.
    """

    responses: list[list[TaskCandidate]] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    fail_times: int = 0
    output_fail_times: int = 0
    calls: int = 0

    async def split_tasks(
        self, *, prompt: str, today: date
    ) -> SplitResult:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMFailedError("simulated LLM failure")
        if self.output_fail_times > 0:
            self.output_fail_times -= 1
            raise LLMOutputError("simulated unparseable output")
        tasks = self.responses.pop(0)
        intent = self.intents.pop(0) if self.intents else "plan"
        return SplitResult(intent=intent, tasks=tasks)
