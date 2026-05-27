from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMPort(Protocol):
    async def generate(self, prompt: str) -> str: ...


class ImageGeneratorPort(Protocol):
    async def generate_img2img(self, reference_url: str, prompt: str) -> bytes: ...


class S3Port(Protocol):
    async def upload(self, key: str, data: bytes) -> str: ...


@dataclass
class Ports:
    llm: LLMPort
    image_generator: ImageGeneratorPort
    s3: S3Port
