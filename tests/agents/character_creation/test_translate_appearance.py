from __future__ import annotations

from agents.character_creation.nodes.translate_appearance import (
    translate_appearance_node,
)
from agents.character_creation.schemas import LLMPersonaResult
from tests.agents.character_creation.fakes import FakeTranslator


def _state(appearance: str = "둥근 갈색 몸"):
    return {
        "llm_result": LLMPersonaResult(
            personality="p", speech_style="s", background="b", appearance=appearance
        )
    }


def _cfg(translator):
    ports = type("_P", (), {"translator": translator})()
    return {"configurable": {"ports": ports}}


async def test_translates_appearance_to_english() -> None:
    tr = FakeTranslator(result="round brown body")
    out = await translate_appearance_node(_state(), _cfg(tr))
    assert out["llm_result"].appearance == "round brown body"
    assert tr.last_input == "둥근 갈색 몸"


async def test_other_persona_fields_unchanged() -> None:
    out = await translate_appearance_node(_state(), _cfg(FakeTranslator(result="en")))
    r = out["llm_result"]
    assert (r.personality, r.speech_style, r.background) == ("p", "s", "b")


async def test_translation_failure_keeps_korean_original() -> None:
    out = await translate_appearance_node(_state(), _cfg(FakeTranslator(fail=True)))
    assert out == {}  # state 미변경 → 원본 한국어 appearance 유지


async def test_empty_translation_keeps_original() -> None:
    out = await translate_appearance_node(_state(), _cfg(FakeTranslator(result="   ")))
    assert out == {}
