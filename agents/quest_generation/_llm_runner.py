from __future__ import annotations

import re

from agents.quest_generation.exceptions import LLMFailedError
from agents.quest_generation.protocols import LLMPort
from agents.quest_generation.schemas import Character

_NON_KO = re.compile(r"[一-鿿぀-ヿ]")  # 중국어/일본어(한자·가나) 차단
_HANGUL = re.compile(r"[가-힣]")


def _validate_korean(text: str) -> None:
    """퀘스트가 한국어인지 검증. 아니면 LLMFailedError 로 재시도를 유도한다."""
    if _NON_KO.search(text) or not _HANGUL.search(text):
        raise LLMFailedError(f"non-Korean quest_text: {text!r}")


class LLMRunner:
    """Calls LLMPort with bounded retry. Re-raises the last LLMFailedError on exhaustion."""

    def __init__(self, llm: LLMPort, *, max_retries: int = 2) -> None:
        self._llm = llm
        self._max_retries = max_retries

    async def generate(self, *, character: Character) -> str:
        last_err: LLMFailedError | None = None
        for _ in range(self._max_retries + 1):
            try:
                text = await self._llm.generate_quest(character=character)
                # 비한국어/이상한 언어면 재시도(provider 무관하게 여기서 한 번 더 거른다).
                _validate_korean(text)
                return text
            except LLMFailedError as err:
                last_err = err
                continue
        assert last_err is not None
        raise last_err
