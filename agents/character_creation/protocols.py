from __future__ import annotations

from typing import Protocol

from agents.character_creation.schemas import (
    CharacterEntity,
    ImageGenerationResult,
    LLMPersonaResult,
    PersonalityKeyword,
)


class LLMPort(Protocol):
    async def generate_persona(
        self,
        *,
        name: str,
        persona: str,
        keywords: list[PersonalityKeyword],
    ) -> LLMPersonaResult: ...


class S3Port(Protocol):
    async def put_object(self, *, key: str, body: bytes, content_type: str) -> str: ...
    async def delete_object(self, *, key: str) -> None: ...


class ImageGeneratorPort(Protocol):
    async def generate(
        self,
        *,
        user_id: str,
        llm_result: LLMPersonaResult,
        fallback_persona: str | None,
        source_image_bytes: bytes | None,
    ) -> ImageGenerationResult: ...


class CharacterRepositoryPort(Protocol):
    async def increment(self, user_id: str) -> int: ...
    async def save(self, entity: CharacterEntity) -> None: ...
