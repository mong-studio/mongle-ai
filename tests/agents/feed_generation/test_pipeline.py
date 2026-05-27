import pytest
from agents.feed_generation import pipeline
from agents.feed_generation.exceptions import (
    CaptionValidationError,
    ImageGenerationError,
    S3UploadError,
)
from agents.feed_generation.schemas import GeneratedFeed
from tests.agents.feed_generation.fakes import (
    FakeLLM,
    FailingImageGenerator,
    FailingS3,
    make_input,
    make_ports,
)


async def test_pipeline_run_returns_generated_feed():
    inp = make_input()
    ports = make_ports()

    result = await pipeline.run(inp, ports=ports)

    assert isinstance(result, GeneratedFeed)
    assert result.character_id == inp.character.character_id
    assert result.quest_id == inp.quest.quest_id
    assert result.image_url.startswith("https://")
    assert len(result.caption) <= 140


async def test_pipeline_run_propagates_image_generation_error_after_retries():
    inp = make_input()
    ports = make_ports(image_generator=FailingImageGenerator())

    with pytest.raises(ImageGenerationError):
        await pipeline.run(inp, ports=ports)


async def test_pipeline_run_propagates_s3_upload_error_after_retries():
    inp = make_input()
    ports = make_ports(s3=FailingS3())

    with pytest.raises(S3UploadError):
        await pipeline.run(inp, ports=ports)


async def test_pipeline_run_propagates_caption_validation_error_for_non_korean():
    inp = make_input()
    ports = make_ports(llm=FakeLLM(caption="Cleaned my room! Great day!"))

    with pytest.raises(CaptionValidationError) as exc_info:
        await pipeline.run(inp, ports=ports)
    assert exc_info.value.code == "no_korean"


async def test_pipeline_run_propagates_caption_validation_error_for_too_long():
    inp = make_input()
    ports = make_ports(llm=FakeLLM(caption="가" * 141))

    with pytest.raises(CaptionValidationError) as exc_info:
        await pipeline.run(inp, ports=ports)
    assert exc_info.value.code == "caption_too_long"
