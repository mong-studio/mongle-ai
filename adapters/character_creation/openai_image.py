from __future__ import annotations

import base64
from typing import Any

from adapters.character_creation._prompts import load as load_prompt
from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.schemas import LLMPersonaResult, VLMResult

_STYLE_GUARD = load_prompt("image_gen_v1")


class OpenAIImageGenerator:
    """Implements ImageGeneratorPort using OpenAI gpt-image-1."""

    def __init__(
        self,
        *,
        client: Any,
        model: str = "gpt-image-1",
        size: str = "1024x1024",
    ) -> None:
        self._client = client
        self._model = model
        self._size = size

    def _build_prompt(
        self,
        *,
        llm_result: LLMPersonaResult,
        vlm_result: VLMResult | None,
        fallback_persona: str | None,
    ) -> str:
        traits = [
            f"Personality: {llm_result.personality}",
            f"Background: {llm_result.background}",
        ]
        if vlm_result is not None:
            traits.append(f"Appearance: {vlm_result.appearance_description}")
        elif fallback_persona is not None:
            traits.append(f"Persona hint: {fallback_persona}")
        return _STYLE_GUARD + "\n\n" + "\n".join(traits)

    async def generate(
        self,
        *,
        user_id: str,
        llm_result: LLMPersonaResult,
        vlm_result: VLMResult | None,
        fallback_persona: str | None,
    ) -> bytes:
        prompt = self._build_prompt(
            llm_result=llm_result,
            vlm_result=vlm_result,
            fallback_persona=fallback_persona,
        )
        try:
            response = self._client.images.generate(
                model=self._model,
                prompt=prompt,
                size=self._size,
                n=1,
            )
        except Exception as err:
            raise ImageGenerationFailedError(f"OpenAI image generate failed: {err}") from err

        if not getattr(response, "data", None):
            raise ImageGenerationFailedError("OpenAI image response had no data")

        b64 = getattr(response.data[0], "b64_json", None)
        if not b64:
            raise ImageGenerationFailedError("OpenAI image response missing b64_json")

        try:
            return base64.b64decode(b64)
        except (ValueError, TypeError) as err:
            raise ImageGenerationFailedError(f"Failed to decode b64 image: {err}") from err
