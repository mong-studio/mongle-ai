from __future__ import annotations

from agents.character_creation.schemas import (
    LLMPersonaResult,
    PersonalityKeyword,
)


class FakeLLM:
    """Small local fallback for image-worker integration tests."""

    async def generate_persona(
        self,
        *,
        name: str,
        persona: str,
        keywords: list[PersonalityKeyword],
    ) -> LLMPersonaResult:
        keyword_text = ", ".join(str(keyword.value) for keyword in keywords)
        appearance = persona.strip() or name
        personality = keyword_text or "friendly"
        return LLMPersonaResult(
            personality=personality,
            speech_style="casual and warm",
            background=f"{name} was created from a local FastAPI integration test.",
            appearance=appearance,
            appearance_en=appearance,
        )
