from __future__ import annotations

import logging
from datetime import date
from typing import Any

from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.single_turn.state import GenerateGraphState

logger = logging.getLogger(__name__)

MAX_TASKS = 20


def _correct(task: TaskCandidate, today: date) -> TaskCandidate:
    due = task.due_date if task.due_date >= today else today
    if due == task.due_date:
        return task
    logger.info(
        "task_splitter: past due_date %s corrected to today %s (title=%r)",
        task.due_date, today, task.title,
    )
    return task.model_copy(update={"due_date": due})


async def task_splitter_node(
    state: GenerateGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    today = state["input"].today

    raw = await ports.llm.split_tasks(prompt=state["input"].prompt, today=today)
    if not raw:
        # B2: one retry on empty
        raw = await ports.llm.split_tasks(prompt=state["input"].prompt, today=today)
        if not raw:
            raise LLMOutputError("task_splitter returned empty list after retry")

    if len(raw) > MAX_TASKS:
        raise LLMOutputError(
            f"task_splitter returned {len(raw)} tasks (max {MAX_TASKS})"
        )

    corrected = [_correct(t, today) for t in raw]
    return {"split_tasks": corrected}
