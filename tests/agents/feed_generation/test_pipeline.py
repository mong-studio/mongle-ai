import pytest
from pydantic import ValidationError

from agents.feed_generation import pipeline
from agents.feed_generation.exceptions import ImageGenerationError, S3UploadError
from agents.feed_generation.schemas import GeneratedFeed
from tests.agents.feed_generation.fakes import (
    FailingImageGenerator,
    FailingS3,
    FakeImageGenerator,
    FakeLLM,
    make_input,
    make_ports,
)

pytestmark = pytest.mark.asyncio

# gen_feed_prompt 는 LLM 을 호출하지 않는다 → 파이프라인의 유일한 LLM 콜은 캡션이다.


async def test_run_happy_path_produces_feed():
    inp = make_input()
    ports = make_ports(image_generator=FakeImageGenerator())  # 기본 FakeLLM = 한국어 캡션
    result = await pipeline.run(inp, ports=ports)
    assert isinstance(result, GeneratedFeed)
    assert result.character_id == inp.character.character_id
    assert result.quest_id == inp.quest.quest_id
    assert result.image_url.startswith("https://")
    assert len(result.caption) <= 140


async def test_run_feed_image_receives_quest_prompts():
    gen = FakeImageGenerator()
    inp = make_input()
    await pipeline.run(inp, ports=make_ports(image_generator=gen))
    ref, char, scene, appearance_payload = gen.feed_calls[0]
    assert ref == inp.character.image_url
    assert appearance_payload == inp.character.appearance_payload
    assert "방 청소하기" in char   # quest = action
    assert scene == "방 청소하기"    # quest = scene (pass-through)


async def test_run_propagates_image_generation_error_after_retries():
    ports = make_ports(image_generator=FailingImageGenerator())
    with pytest.raises(ImageGenerationError):
        await pipeline.run(make_input(), ports=ports)


async def test_run_propagates_s3_upload_error_after_retries():
    ports = make_ports(image_generator=FakeImageGenerator(), s3=FailingS3())
    with pytest.raises(S3UploadError):
        await pipeline.run(make_input(), ports=ports)


async def test_run_rejects_non_korean_caption_at_builder():
    # 캡션 검증은 builder 의 GeneratedFeed 스키마(한글 필수) → pydantic ValidationError
    ports = make_ports(image_generator=FakeImageGenerator(), llm=FakeLLM(response="Cleaned my room!"))
    with pytest.raises(ValidationError):
        await pipeline.run(make_input(), ports=ports)


async def test_run_rejects_too_long_caption_at_builder():
    ports = make_ports(image_generator=FakeImageGenerator(), llm=FakeLLM(response="가" * 141))
    with pytest.raises(ValidationError):
        await pipeline.run(make_input(), ports=ports)
