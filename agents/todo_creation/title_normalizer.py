"""Title normalizer for TODO/calendar tasks.

LLM 이 발화를 그대로 잘라서 title 로 내보내는 경우의 안전망.
시간·장소 부사구를 앞에서 제거하고, 동사 어미를 뒤에서 제거해 명사구로 만든다.

한계: 한국어 활용형은 형태소 분석기 없이 완벽 처리 불가.
LLM prompt 가 1차 정규화를 담당하고, 본 모듈은 누락분만 수습한다.
"""
from __future__ import annotations

import re

# "오늘 집 가서" 같은 부사구 합성 최대 깊이 (실측상 2 합성이 최대)
MAX_LEADING_PASSES = 3

_LEADING_PATTERNS = [
    re.compile(r"^오늘\s+"),
    re.compile(r"^내일\s+"),
    re.compile(r"^모레\s+"),
    re.compile(r"^어제\s+"),
    re.compile(r"^이따(가)?\s+"),
    re.compile(r"^지금\s+"),
    re.compile(r"^(아침|저녁|오전|오후|밤|새벽)에\s+"),
    re.compile(r"^\S+\s+가서\s+"),
    re.compile(r"^가서\s+"),
    re.compile(r"^회사(에|에서)?\s+"),
    re.compile(r"^학교(에|에서)?\s+"),
    re.compile(r"^퇴근하고\s+"),
    re.compile(r"^출근하고\s+"),
]

# "하다" 동사 활용형: 명사 어근만 남기고 모두 제거
_VERB_TAIL_HADA = re.compile(
    r"(하고|할거야|할 거야|하려고|해야지|할 예정|하고 싶어|하려|할까|할까요)$"
)

# 비-"하다" 동사 어간 → 명사형 매핑. 매핑되면 "{head} {명사형}" 으로 보존,
# 없으면 동사를 떼고 head 만 남긴다 (보수적 fallback).
_VERB_NOUN_MAP: dict[str, str] = {
    "짜": "작성",
    "쓰": "작성",
    "끝내": "완료",
    "마치": "완료",
    "만들": "제작",
    "보내": "발송",
    "고치": "수정",
    "읽": "독서",
}

# "{head}을/를 {verb_stem}{ending}" 형태 캡처.
# 어미 alternation 은 긴 것부터 매칭되도록 길이 내림차순 배치.
_OBJ_VERB_TAIL = re.compile(
    r"^(?P<head>.+?)\s*(을|를)\s*"
    r"(?P<verb>\S+?)"
    r"(?P<ending>고 싶어|어야지|을 거야|을거야|으려고|야지|거야|려고|으려|고|야|어|지|냐|기|러|려|면|니)$"
)

_LEFTOVER_OBJ_PARTICLE = re.compile(r"(을|를)\s+(\S+)$")


def _strip_obj_verb_tail(s: str) -> str:
    """'X을/를 V어미' → 'X {V의 명사형}' (매핑 시) 또는 'X' (fallback)."""
    m = _OBJ_VERB_TAIL.match(s)
    if not m:
        return s
    head = m.group("head").strip()
    noun = _VERB_NOUN_MAP.get(m.group("verb"))
    return f"{head} {noun}" if noun else head


def normalize_title(title: str, max_len: int = 80) -> str:
    """Normalize a natural-language task title into a short noun phrase.

    Strips leading temporal/place phrases and trailing verb endings.
    Returns the original (truncated) on degenerate inputs.
    """
    s = title.strip()
    if not s:
        return title[:max_len]

    # 1. Strip leading time/place phrases (iterate for compound like "오늘 집 가서")
    for _ in range(MAX_LEADING_PASSES):
        changed = False
        for pat in _LEADING_PATTERNS:
            new = pat.sub("", s)
            if new != s:
                s = new.strip()
                changed = True
        if not changed:
            break

    # 2. Strip "하다" verb endings while preserving the noun root
    after_hada = _VERB_TAIL_HADA.sub("", s).rstrip()
    if after_hada != s and after_hada:
        # collapse leftover "X을/를 Y" → "X Y"
        after_hada = _LEFTOVER_OBJ_PARTICLE.sub(r" \2", after_hada).strip()
        s = after_hada
    else:
        # 3. Non-하다 verb at end: verb 를 명사형으로 매핑 후 보존
        after_obj = _strip_obj_verb_tail(s)
        if after_obj:
            s = after_obj

    s = s.strip()
    if not s:
        return title[:max_len]
    return s[:max_len]
