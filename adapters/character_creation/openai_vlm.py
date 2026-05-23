from __future__ import annotations

import base64
import json
from typing import Any

from pydantic import ValidationError

from adapters.character_creation._prompts import load as load_prompt
from agents.character_creation.exceptions import VLMFailedError
from agents.character_creation.schemas import SourceImage, VLMResult

_SYSTEM_PROMPT = load_prompt("vlm_appearance_v1")


def _strict_schema() -> dict[str, Any]:
    schema = VLMResult.model_json_schema()
    schema["additionalProperties"] = False
    return schema


class OpenAIVLM:
    """Implements VLMPort using OpenAI Chat Completions multimodal input."""

    def __init__(self, *, client: Any, model: str = "gpt-4o") -> None:
        self._client = client
        self._model = model

    async def extract_appearance(self, image: SourceImage) -> VLMResult:
        b64 = base64.b64encode(image.data).decode("ascii")
        data_url = f"data:{image.content_type};base64,{b64}"

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "다음 이미지의 외형을 분석하라."},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "VLMResult",
                        "schema": _strict_schema(),
                        "strict": True,
                    },
                },
            )
        except Exception as err:
            raise VLMFailedError(f"OpenAI VLM call failed: {err}") from err

        content = response.choices[0].message.content
        try:
            data = json.loads(content)
        except (TypeError, json.JSONDecodeError) as err:
            raise VLMFailedError(f"Invalid JSON: {content!r}") from err

        try:
            return VLMResult(**data)
        except ValidationError as err:
            raise VLMFailedError(f"Schema mismatch: {err}") from err
