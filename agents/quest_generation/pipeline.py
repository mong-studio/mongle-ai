from __future__ import annotations

from dataclasses import dataclass

from agents.quest_generation._llm_runner import LLMRunner
from agents.quest_generation._pool import CharacterPool
from agents.quest_generation.exceptions import LLMFailedError
from agents.quest_generation.protocols import LLMPort
from agents.quest_generation.schemas import (
    GeneratedQuest,
    QuestDistributionResult,
    QuestGenerationInput,
    SkippedItem,
)


@dataclass
class Ports:
    llm: LLMPort


async def run(
    input: QuestGenerationInput,
    *,
    ports: Ports,
) -> QuestDistributionResult:
    cap = min(len(input.todos), input.remaining_daily_quota)
    if cap <= 0 or not input.characters:
        return QuestDistributionResult(generated=[], skipped=[])

    pool = CharacterPool(input.characters, seed=input.shuffle_seed)
    runner = LLMRunner(ports.llm, max_retries=2)

    generated: list[GeneratedQuest] = []
    skipped: list[SkippedItem] = []

    for todo in input.todos[:cap]:
        char = pool.next()
        try:
            text = await runner.generate(character=char)
            generated.append(
                GeneratedQuest(
                    character_id=char.character_id,
                    todo_id=todo.todo_id,
                    quest_text=text,
                )
            )
        except LLMFailedError:
            skipped.append(
                SkippedItem(todo_id=todo.todo_id, reason="llm_failure")
            )

    return QuestDistributionResult(generated=generated, skipped=skipped)
