from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.schemas import SplitResult
from agents.todo_creation.todo.state import GenerateGraphState

logger = logging.getLogger(__name__)

MAX_TASKS = 20


async def task_splitter_node(
    state: GenerateGraphState, config: RunnableConfig
) -> dict[str, Any]:
    # split_tasks(뉴로-심볼릭)가 task별 when 구문 추출 + 절대날짜 변환(과거 클램프 포함)을
    # 모두 끝낸 TaskCandidate 를 돌려준다. 노드는 분기/한도 검증만 한다.
    ports = get_ports(config)
    today = state["input"].today

    split: SplitResult = await ports.llm.split_tasks(
        prompt=state["input"].prompt, today=today
    )
    if split.intent == "out_of_scope":
        return {"intent": "out_of_scope"}

    raw = split.tasks
    if not raw:
        # B2: one retry on empty (plan 인데 비었을 때만)
        split = await ports.llm.split_tasks(
            prompt=state["input"].prompt, today=today
        )
        if split.intent == "out_of_scope":
            return {"intent": "out_of_scope"}
        raw = split.tasks
        if not raw:
            raise LLMOutputError("task_splitter returned empty list after retry")

    if len(raw) > MAX_TASKS:
        raise LLMOutputError(
            f"task_splitter returned {len(raw)} tasks (max {MAX_TASKS})"
        )

    return {"intent": "plan", "split_tasks": list(raw)}
