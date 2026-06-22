import pytest
from pydantic import ValidationError

from agents.feed_generation import pipeline
from agents.feed_generation.exceptions import ImageGenerationError, S3UploadError
from agents.feed_generation.schemas import GeneratedFeed
from tests.agents.feed_generation.fakes import (
    FailingImageGenerator,
    FailingS3,
    FakeImageGenerator,
    ScriptedLLM,
    make_input,
    make_ports,
)

pytestmark = pytest.mark.asyncio

# gen_feed_prompt 는 LLM 1콜(action/scene), llm_caption 은 LLM 1콜(캡션) — 호출 순서대로.
_PROMPT_REPLY = "action: cleaning a room\nscene: cozy bedroom"


async def test_run_happy_path_produces_feed():
    inp = make_input()
    llm = ScriptedLLM([_PROMPT_REPLY, "방 청소 끝! 뿌듯해 ✨"])
    ports = make_ports(llm=llm, image_generator=FakeImageGenerator())

    result = await pipeline.run(inp, ports=ports)

    assert isinstance(result, GeneratedFeed)
    assert result.character_id == inp.character.character_id
    assert result.quest_id == inp.quest.quest_id
    assert result.caption == "방 청소 끝! 뿌듯해 ✨"
    assert result.image_url.startswith("https://")
    assert len(llm.calls) == 2


async def test_run_feed_image_receives_split_prompts():
    llm = ScriptedLLM(["action: watering plants\nscene: sunny balcony", "식물에 물 줬어 🌱"])
    gen = FakeImageGenerator()
    inp = make_input()
    await pipeline.run(inp, ports=make_ports(llm=llm, image_generator=gen))
    ref, char, scene = gen.feed_calls[0]
    assert ref == inp.character.image_url
    assert "watering plants" in char
    assert scene == "sunny balcony"


async def test_run_propagates_image_generation_error_after_retries():
    llm = ScriptedLLM([_PROMPT_REPLY] * 4)  # gen_feed_prompt 만 도달, feed_image 에서 실패
    ports = make_ports(llm=llm, image_generator=FailingImageGenerator())
    with pytest.raises(ImageGenerationError):
        await pipeline.run(make_input(), ports=ports)


async def test_run_propagates_s3_upload_error_after_retries():
    llm = ScriptedLLM([_PROMPT_REPLY])
    ports = make_ports(llm=llm, image_generator=FakeImageGenerator(), s3=FailingS3())
    with pytest.raises(S3UploadError):
        await pipeline.run(make_input(), ports=ports)


async def test_run_rejects_non_korean_caption_at_builder():
    # 캡션 검증은 builder 의 GeneratedFeed 스키마(한글 필수) → pydantic ValidationError
    llm = ScriptedLLM([_PROMPT_REPLY, "Cleaned my room! Great day!"])
    ports = make_ports(llm=llm, image_generator=FakeImageGenerator())
    with pytest.raises(ValidationError):
        await pipeline.run(make_input(), ports=ports)


async def test_run_rejects_too_long_caption_at_builder():
    llm = ScriptedLLM([_PROMPT_REPLY, "가" * 141])
    ports = make_ports(llm=llm, image_generator=FakeImageGenerator())
    with pytest.raises(ValidationError):
        await pipeline.run(make_input(), ports=ports)
