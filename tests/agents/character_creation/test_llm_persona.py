from __future__ import annotations

import pytest

from agents.character_creation.exceptions import LLMFailedError
from agents.character_creation.nodes.llm_persona import llm_persona_node
from agents.character_creation.schemas import CharacterCreationInput
from agents.character_creation.state import CharacterGraphState
from tests.agents.character_creation.fakes import FakeLLM


def _state() -> CharacterGraphState:
    return CharacterGraphState(
        input=CharacterCreationInput(user_id="u1", name="몽글이", persona="다정한 곰"),
        is_regeneration=False,
    )


def _config(llm: FakeLLM) -> dict:
    class _Ports:
        pass
    p = _Ports()
    p.llm = llm
    return {"configurable": {"ports": p}}


async def test_llm_persona_node_returns_result_dict() -> None:
    llm = FakeLLM()
    out = await llm_persona_node(_state(), _config(llm))
    assert out["llm_result"].personality.startswith("성격:")
    assert llm.calls == 1


async def test_llm_persona_node_propagates_failure_for_retry_policy() -> None:
    llm = FakeLLM(fail_times=1)
    with pytest.raises(LLMFailedError):
        await llm_persona_node(_state(), _config(llm))
    assert llm.calls == 1
