from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_SYSTEM = "너는 시험 준비 계획을 자연스럽고 간결하게 한국어로 다듬는 도우미다. 사실을 추가하지 말고 표현만 정리해라."


def rephrase(
    text: str,
    *,
    use_llm: bool = False,
    client=None,
    model: str = "gpt-4o-mini",
    temperature: float = 0.3,
) -> tuple[str, str]:
    if not use_llm or client is None:
        return text, "template"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=temperature,
        )
        return resp.choices[0].message.content, "llm"
    except Exception as exc:
        log.warning("rephrase LLM 호출 실패, 템플릿으로 폴백: %s", exc)
        return text, "template"


def make_client():
    """OPENAI_API_KEY가 있으면 openai 클라이언트 생성, 없으면 None."""
    import os

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    from openai import OpenAI

    return OpenAI(api_key=key)
