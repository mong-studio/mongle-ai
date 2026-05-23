from __future__ import annotations

import pytest

from agents.character_creation.exceptions import LLMFailedError, S3UploadFailedError
from tests.agents.character_creation.fakes import FakeLLM, FakeS3


async def test_fake_llm_returns_struct_after_failures() -> None:
    llm = FakeLLM(fail_times=2)
    with pytest.raises(LLMFailedError):
        await llm.generate_persona(persona="x", keywords=[])
    with pytest.raises(LLMFailedError):
        await llm.generate_persona(persona="x", keywords=[])
    result = await llm.generate_persona(persona="hello", keywords=[])
    assert result.personality.startswith("성격:")
    assert llm.calls == 3


async def test_fake_s3_stores_bytes_under_key() -> None:
    s3 = FakeS3()
    url = await s3.put_object(key="k", body=b"abc", content_type="image/png")
    assert url.endswith("/k")
    assert s3.stored["k"] == b"abc"


async def test_fake_s3_simulates_failure() -> None:
    s3 = FakeS3(fail_times=1)
    with pytest.raises(S3UploadFailedError):
        await s3.put_object(key="k", body=b"abc", content_type="image/png")
    url = await s3.put_object(key="k", body=b"abc", content_type="image/png")
    assert url
