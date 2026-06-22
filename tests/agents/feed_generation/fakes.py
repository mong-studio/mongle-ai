from __future__ import annotations

import io
from uuid import uuid4

from PIL import Image

from agents.feed_generation.exceptions import (
    ImageGenerationError,
    S3UploadError,
)
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import CharacterRef, FeedGenerationInput, QuestRef
from agents.feed_generation.state import FeedGraphState


def make_input(**overrides) -> FeedGenerationInput:
    data = dict(
        quest=QuestRef(quest_id=uuid4(), quest="방 청소하기"),
        character=CharacterRef(
            character_id=uuid4(),
            name="몽글이",
            personality="밝고 활발함",
            speech_style="반말, 이모티콘 자주 사용",
            visual=["분홍색 머리", "큰 눈", "귀여운"],
            image_url="https://s3.example.com/characters/test.png",
        ),
    )
    data.update(overrides)
    return FeedGenerationInput(**data)


def _tiny_png(mode: str, color, size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


# composite 노드가 실제 PIL 로 여는 유효 PNG (배경=RGB)
_FAKE_BG_PNG = _tiny_png("RGB", (0, 0, 255))


def make_state(**overrides) -> FeedGraphState:
    defaults = {
        "input": make_input(),
        "feed_prompt": None,
        "raw_image": None,
        "image_url": None,
        "caption_prompt": None,
        "raw_caption": None,
        "result": None,
    }
    defaults.update(overrides)
    return defaults


class FakeLLM:  # 단일 응답 (캡션 노드용)
    def __init__(self, response: str = "오늘 방 청소 완료! 기분 최고 ✨") -> None:
        self.response = response
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response


class ScriptedLLM:  # 호출별 다른 응답 (파이프라인 통합 테스트용)
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.responses.pop(0)


class FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise RuntimeError("LLM 서버 오류")


class FakeImageGenerator:
    def __init__(self, image_bytes: bytes = _FAKE_BG_PNG) -> None:
        self.image_bytes = image_bytes
        self.feed_calls: list[tuple[str, str, str]] = []

    async def generate_feed(
        self, reference_url: str, character_prompt: str, scene_prompt: str
    ) -> bytes:
        self.feed_calls.append((reference_url, character_prompt, scene_prompt))
        return self.image_bytes


class FailingImageGenerator:
    async def generate_feed(
        self, reference_url: str, character_prompt: str, scene_prompt: str
    ) -> bytes:
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
