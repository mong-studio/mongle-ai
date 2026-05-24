from __future__ import annotations

from typing import Protocol

from agents.character_creation.schemas import (
    CharacterEntity,
    LLMPersonaResult,
    PersonalityKeyword,
    SourceImage,
    VLMResult,
)


class LLMPort(Protocol):
    async def generate_persona(
        self,
        *,
        persona: str,
        keywords: list[PersonalityKeyword],
    ) -> LLMPersonaResult: ...


class VLMPort(Protocol):
    async def extract_appearance(self, image: SourceImage) -> VLMResult: ...


class S3Port(Protocol):
    async def put_object(self, *, key: str, body: bytes, content_type: str) -> str: ...
    async def delete_object(self, *, key: str) -> None: ...


class ImageGeneratorPort(Protocol):
    async def generate(
        self,
        *,
        user_id: str,
        llm_result: LLMPersonaResult,
        vlm_result: VLMResult | None,
        fallback_persona: str | None,
    ) -> bytes: ...


class CharacterRepositoryPort(Protocol):
    async def increment(self, user_id: str) -> int: ...
    async def save(self, entity: CharacterEntity) -> None: ...
