from __future__ import annotations

from typing import Protocol

from agents.character_creation.schemas import (
    CharacterEntity,
    LLMPersonaResult,
    PersonalityKeyword,
)


class LLMPort(Protocol):
    async def generate_persona(
        self,
        *,
        persona: str,
        keywords: list[PersonalityKeyword],
    ) -> LLMPersonaResult: ...


class TranslatorPort(Protocol):
    async def translate_appearance(self, korean: str) -> str:
        """한국어 외형 묘사를 이미지용 영어 visual 태그로 변환한다."""
        ...


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
    ) -> bytes: ...


class CharacterRepositoryPort(Protocol):
    async def increment(self, user_id: str) -> int: ...
    async def save(self, entity: CharacterEntity) -> None: ...
