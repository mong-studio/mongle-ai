from __future__ import annotations

import json
from datetime import date

import pytest

from agents.todo_creation.exceptions import LLMOutputError


@pytest.fixture
def patch_openai(mocker):
    """Patch the OpenAI client.chat.completions.create call.

    Returns a helper that takes the JSON string the model 'produces' and wires
    it through the mocked SDK response.
    """
    pytest.importorskip("openai")

    def _install(response_json: str):
        from adapters.todo_creation import openai_llm

        mock_client = mocker.MagicMock()
        mock_message = mocker.MagicMock(content=response_json)
        mock_choice = mocker.MagicMock(message=mock_message)
        mock_client.chat.completions.create = mocker.AsyncMock(
            return_value=mocker.MagicMock(choices=[mock_choice])
        )
        mocker.patch.object(
            openai_llm, "_get_client", return_value=mock_client
        )
        return mock_client

    return _install


async def test_split_tasks_parses_valid_json(patch_openai) -> None:
    from adapters.todo_creation.openai_llm import OpenAILLM

    payload = json.dumps(
        {
            "tasks": [
                {"title": "코테", "due_date": "2026-05-24", "time_hint": "오전"},
                {"title": "발표", "due_date": "2026-05-27", "time_hint": None},
            ]
        }
    )
    patch_openai(payload)

    llm = OpenAILLM(model="gpt-4o-mini")
    out = await llm.split_tasks(
        prompt="오늘 코테, 3일 뒤 발표", today=date(2026, 5, 24)
    )
    assert len(out) == 2
    assert out[0].title == "코테"
    assert out[0].time_hint == "오전"


async def test_split_tasks_today_is_in_prompt(patch_openai) -> None:
    from adapters.todo_creation.openai_llm import OpenAILLM

    mock_client = patch_openai(json.dumps({"tasks": []}))

    llm = OpenAILLM(model="gpt-4o-mini")
    await llm.split_tasks(prompt="x", today=date(2026, 5, 24))

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    serialized = json.dumps(call_kwargs.get("messages"), default=str)
    assert "2026-05-24" in serialized


async def test_split_tasks_invalid_json_raises_llm_output_error(
    patch_openai,
) -> None:
    from adapters.todo_creation.openai_llm import OpenAILLM

    patch_openai("not valid json at all")
    llm = OpenAILLM(model="gpt-4o-mini")
    with pytest.raises(LLMOutputError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))


async def test_split_tasks_missing_tasks_key_raises(patch_openai) -> None:
    from adapters.todo_creation.openai_llm import OpenAILLM

    patch_openai(json.dumps({"unrelated": []}))
    llm = OpenAILLM(model="gpt-4o-mini")
    with pytest.raises(LLMOutputError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))
