from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class LLMPort(Protocol):
    async def generate(self, prompt: str) -> str: ...


class ImageGeneratorPort(Protocol):
    async def generate_feed(
        self,
        reference_url: str,
        character_prompt: str,
        scene_prompt: str,
        appearance_payload: dict[str, Any] | None = None,
    ) -> bytes: ...


class S3Port(Protocol):
    async def upload(self, key: str, data: bytes) -> str: ...


@dataclass
class Ports:
    llm: LLMPort
    image_generator: ImageGeneratorPort
    s3: S3Port
