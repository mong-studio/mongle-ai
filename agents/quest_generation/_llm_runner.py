from __future__ import annotations

import re

from agents.quest_generation.exceptions import LLMFailedError
from agents.quest_generation.protocols import LLMPort
from agents.quest_generation.schemas import Character

_HANGUL = re.compile(r"[가-힣]")
# 허용(한글·숫자·공백·일반 문장부호) 외 문자가 하나라도 있으면 외국어로 본다.
# 기존 denylist([一-鿿぀-ヿ])는 중국어·일본어만 막아 베트남어('giải')·영어 등이 통과했다.
_FOREIGN = re.compile(
    r"[^가-힣ㄱ-ㅎㅏ-ㅣ0-9\s.,!?~…·\-'\"“”‘’()\[\]%\U0001F000-\U0001FAFF☀-➿️‍]"
)


def _validate_korean(text: str) -> None:
    """퀘스트가 한국어인지 검증. 한글이 없거나 허용 외 문자(모든 외국어)가 있으면 재시도를 유도한다."""
    if not _HANGUL.search(text) or _FOREIGN.search(text):
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
