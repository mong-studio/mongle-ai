from __future__ import annotations

import pytest

from adapters._shared.runpod_client import RunPodJobError
from adapters.character_creation.runpod_translator import RunPodTranslator
from agents.character_creation.exceptions import LLMFailedError

ENDPOINT = "https://api.runpod.ai/v2/test-ep"
_MOD = "adapters.character_creation.runpod_translator"


async def test_translate_sends_base_adapter_and_strips_text(monkeypatch) -> None:
    seen: dict = {}

    async def fake_run_and_poll(**kwargs):
        seen.update(kwargs)
        return {"text": "  cute brown bear, yellow scarf  "}

    monkeypatch.setattr(f"{_MOD}.run_and_poll", fake_run_and_poll)
    tr = RunPodTranslator(endpoint_url=ENDPOINT, api_key="k")

    result = await tr.translate_appearance("포근한 갈색 곰, 노란 스카프")

    assert result == "cute brown bear, yellow scarf"
    payload_input = seen["payload"]["input"]
    assert payload_input["adapter"] == "base"
    assert payload_input["messages"][-1]["content"] == "포근한 갈색 곰, 노란 스카프"


async def test_translate_wraps_job_error(monkeypatch) -> None:
    async def boom(**kwargs):
        raise RunPodJobError("submit failed")

    monkeypatch.setattr(f"{_MOD}.run_and_poll", boom)
    tr = RunPodTranslator(endpoint_url=ENDPOINT, api_key="k")

    with pytest.raises(LLMFailedError):
        await tr.translate_appearance("여우")
