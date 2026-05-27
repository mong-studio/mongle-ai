from __future__ import annotations

from uuid import uuid4

from agents.feed_generation.exceptions import (
    CaptionGenerationError,
    ImageGenerationError,
    S3UploadError,
)
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import CharacterRef, FeedGenerationInput, QuestRef
from agents.feed_generation.state import FeedGraphState


def make_input(**overrides) -> FeedGenerationInput:
    data = dict(
        quest=QuestRef(quest_id=uuid4(), quest_text="방 청소하기"),
        character=CharacterRef(
            character_id=uuid4(),
            name="몽글이",
            personality="밝고 활발함",
            speech_style="반말, 이모티콘 자주 사용",
            appearance_keywords=["분홍색 머리", "큰 눈", "귀여운"],
            image_url="https://s3.example.com/characters/test.png",
        ),
    )
    data.update(overrides)
    return FeedGenerationInput(**data)


def make_state(**overrides) -> FeedGraphState:
    defaults: FeedGraphState = {
        "input": make_input(),
        "image_prompt": None,
        "raw_image": None,
        "image_url": None,
        "caption_ctx": None,
        "raw_caption": None,
        "result": None,
    }
    defaults.update(overrides)
    return defaults


class FakeLLM:
    def __init__(self, caption: str = "오늘 방 청소 완료! 기분 최고 ✨") -> None:
        self.caption = caption
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.caption


class FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise CaptionGenerationError("LLM 서버 오류")


class FakeImageGenerator:
    def __init__(self, image_bytes: bytes = b"fake_image_bytes") -> None:
        self.image_bytes = image_bytes
        self.calls: list[tuple[str, str]] = []

    async def generate_img2img(self, reference_url: str, prompt: str) -> bytes:
        self.calls.append((reference_url, prompt))
        return self.image_bytes


class FailingImageGenerator:
    async def generate_img2img(self, reference_url: str, prompt: str) -> bytes:
        raise ImageGenerationError("이미지 생성 서버 오류")


class FakeS3:
    def __init__(self, url: str = "https://s3.example.com/feeds/result.png") -> None:
        self.url = url
        self.calls: list[tuple[str, bytes]] = []

    async def upload(self, key: str, data: bytes) -> str:
        self.calls.append((key, data))
        return self.url


class FailingS3:
    async def upload(self, key: str, data: bytes) -> str:
        raise S3UploadError("S3 연결 오류")


def make_ports(**overrides) -> Ports:
    defaults = dict(
        llm=FakeLLM(),
        image_generator=FakeImageGenerator(),
        s3=FakeS3(),
    )
    defaults.update(overrides)
    return Ports(**defaults)
