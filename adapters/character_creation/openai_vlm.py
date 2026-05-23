from __future__ import annotations

import base64
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from adapters.character_creation._prompts import load as load_prompt
from agents.character_creation.exceptions import VLMFailedError
from agents.character_creation.schemas import SourceImage, VLMResult

_SYSTEM_PROMPT = load_prompt("vlm_appearance_v1")


class OpenAIVLM:
    """Implements VLMPort via a LangChain Runnable that yields VLMResult.

    The runnable is expected to be
    ``ChatOpenAI(model=...).with_structured_output(VLMResult, method="json_schema", strict=True)``
    so the LangChain stack enforces the Pydantic schema end-to-end.
    """

    def __init__(self, *, runnable: Any) -> None:
        self._runnable = runnable

    async def extract_appearance(self, image: SourceImage) -> VLMResult:
        b64 = base64.b64encode(image.data).decode("ascii")
        data_url = f"data:{image.content_type};base64,{b64}"

        try:
            result = await self._runnable.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=[
                            {"type": "text", "text": "다음 이미지의 외형을 분석하라."},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ]
                    ),
                ]
            )
        except Exception as err:
            raise VLMFailedError(f"LangChain VLM call failed: {err}") from err

        if not isinstance(result, VLMResult):
            raise VLMFailedError(
                f"Structured output returned wrong type: {type(result).__name__}"
            )
        return result
