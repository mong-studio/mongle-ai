"""답글 생성 파이프라인 (단일 LLM 호출 — langgraph 불필요).

입력(페르소나 + 피드 캡션 + 방문자 댓글)으로 프롬프트를 만들고, LLM 으로
캐릭터 말투의 50자 답글을 생성한다. 출력 검증 실패 시 1회 재시도.

프롬프트는 학습 데이터(build_reply_data.py)와 동일하게 유지한다(train==serve).
"""
from __future__ import annotations

import re

from agents.reply_generation.exceptions import ReplyValidationError
from agents.reply_generation.protocols import Ports
from agents.reply_generation.schemas import GeneratedReply, ReplyGenerationInput

_MAX_LEN = 50
_HANGUL = re.compile(r"[가-힣]")
# 허용(한글·숫자·공백·문장부호·이모지) 외 문자는 외국어로 본다. 기존 denylist 는 중/일만 막아
# 베트남어·영어 등이 통과했다(예: 'giải').
_FOREIGN = re.compile(
    r"[^가-힣ㄱ-ㅎㅏ-ㅣ0-9\s.,!?~…·\-'\"“”‘’()\[\]%\U0001F000-\U0001FAFF☀-➿️‍]"
)


def _build_prompt(inp: ReplyGenerationInput) -> str:
    c = inp.character
    return (
        f"당신은 '{c.name}'이라는 캐릭터입니다.\n"
        f"성격: {c.personality}\n"
        f"말투: {c.speech_style}\n\n"
        f"내가 올린 피드: {inp.post_caption}\n"
        f"방문자 댓글: {inp.user_comment}\n\n"
        "위 댓글에 캐릭터의 말투로 친근하게 답글을 달아주세요.\n"
        "규칙: 반드시 한국어로만 작성, 50자 이하, 답글 텍스트만 출력"
    )


def _validate(text: str) -> str:
    text = text.strip()
    if not text:
        raise ReplyValidationError(code="EMPTY", message="빈 답글")
    if len(text) > _MAX_LEN:
        raise ReplyValidationError(code="TOO_LONG", message=f"답글이 {_MAX_LEN}자를 초과")
    if not _HANGUL.search(text) or _FOREIGN.search(text):
        raise ReplyValidationError(code="NOT_KOREAN", message="한국어가 아닌 답글")
    return text


async def run(reply_input: ReplyGenerationInput, *, ports: Ports) -> GeneratedReply:
    prompt = _build_prompt(reply_input)
    last_err: ReplyValidationError | None = None
    for _ in range(2):
        raw = await ports.llm.generate(prompt)
        try:
            reply_text = _validate(raw)
        except ReplyValidationError as err:
            last_err = err
            continue
        return GeneratedReply(
            character_id=reply_input.character.character_id,
            reply_text=reply_text,
        )
    assert last_err is not None
    raise last_err
