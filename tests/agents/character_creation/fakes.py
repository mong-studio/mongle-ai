from __future__ import annotations

from dataclasses import dataclass, field

from agents.character_creation.exceptions import (
    ImageGenerationFailedError,
    LLMFailedError,
    S3UploadFailedError,
    VLMFailedError,
)
from agents.character_creation.schemas import (
    CharacterEntity,
    LLMPersonaResult,
    PersonalityKeyword,
    SourceImage,
    VLMResult,
)


@dataclass
class FakeLLM:
    fail_times: int = 0
    calls: int = 0

    async def generate_persona(
        self,
        *,
        persona: str,
        keywords: list[PersonalityKeyword],
    ) -> LLMPersonaResult:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMFailedError("simulated LLM failure")
        return LLMPersonaResult(
            personality=f"성격:{persona[:5]}",
            speech_style="존댓말",
            background="조용한 숲에서 옴",
        )


@dataclass
class FakeVLM:
    fail_times: int = 0
    calls: int = 0

    async def extract_appearance(self, image: SourceImage) -> VLMResult:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise VLMFailedError("simulated VLM failure")
        return VLMResult(appearance_description="둥근 갈색 곰")


@dataclass
class FakeS3:
    fail_times: int = 0
    stored: dict[str, bytes] = field(default_factory=dict)
    deleted_keys: list[str] = field(default_factory=list)
    calls: int = 0

    async def put_object(
        self, *, key: str, body: bytes, content_type: str
    ) -> str:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise S3UploadFailedError("simulated S3 failure")
        self.stored[key] = body
        return f"https://fake-s3.local/{key}"

    async def delete_object(self, *, key: str) -> None:
        self.deleted_keys.append(key)
        self.stored.pop(key, None)


@dataclass
class FakeImageGenerator:
    fail_times: int = 0
    calls: int = 0
    last_inputs: dict = field(default_factory=dict)

    async def generate(
        self,
        *,
        user_id: str,
        llm_result: LLMPersonaResult,
        vlm_result: VLMResult | None,
        fallback_persona: str | None,
    ) -> bytes:
        self.calls += 1
        self.last_inputs = {
            "user_id": user_id,
            "llm_result": llm_result,
            "vlm_result": vlm_result,
            "fallback_persona": fallback_persona,
        }
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ImageGenerationFailedError("simulated img gen failure")
        return b"GENERATED_PNG_BYTES"


@dataclass
class FakeRepository:
    saved: list[CharacterEntity] = field(default_factory=list)
    save_should_fail: bool = False
    increments: int = 0

    async def increment(self, user_id: str) -> int:
        self.increments += 1
        return self.increments

    async def save(self, entity: CharacterEntity) -> None:
        if self.save_should_fail:
            raise RuntimeError("simulated DB failure")
        self.saved.append(entity)
