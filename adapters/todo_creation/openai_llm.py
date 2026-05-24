from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import TaskCandidate
from adapters.todo_creation._prompts import (
    TASK_SPLITTER_SYSTEM,
    task_splitter_user,
)

_client_singleton: Any = None


def _get_client() -> Any:
    """Lazily import + construct the OpenAI async client.

    Kept as a separate function so tests can patch it via mocker.patch.object.
    """
    global _client_singleton
    if _client_singleton is None:
        try:
            from openai import AsyncOpenAI
        except ImportError as err:
            raise LLMFailedError(
                "openai SDK not installed (install with `pip install mongle-village[ui]`)"
            ) from err
        _client_singleton = AsyncOpenAI()
    return _client_singleton


@dataclass
class OpenAILLM:
    model: str = "gpt-4o-mini"

    async def split_tasks(
        self, *, prompt: str, today: date
    ) -> list[TaskCandidate]:
        client = _get_client()
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": TASK_SPLITTER_SYSTEM},
                    {"role": "user", "content": task_splitter_user(prompt, today)},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as err:
            raise LLMFailedError(f"openai call failed: {err}") from err

        raw = (response.choices[0].message.content or "") if response.choices else ""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as err:
            raise LLMOutputError(f"non-JSON response: {raw[:200]}") from err

        if not isinstance(parsed, dict) or "tasks" not in parsed:
            raise LLMOutputError(
                f"missing 'tasks' key in response: {raw[:200]}"
            )

        tasks_raw = parsed["tasks"]
        if not isinstance(tasks_raw, list):
            raise LLMOutputError("'tasks' is not a list")

        out: list[TaskCandidate] = []
        for item in tasks_raw:
            try:
                out.append(
                    TaskCandidate(
                        title=item["title"],
                        due_date=date.fromisoformat(item["due_date"]),
                        time_hint=item.get("time_hint"),
                    )
                )
            except (KeyError, ValueError, TypeError) as err:
                raise LLMOutputError(
                    f"invalid task item {item!r}: {err}"
                ) from err
        return out
