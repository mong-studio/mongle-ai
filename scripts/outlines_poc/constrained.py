"""제약 스키마 + 한국어/CJK 판정 헬퍼 (PoC 후보 1+2).

후보 2(JSON 강제): SplitResult 모양을 그대로 제약 스키마로 옮긴다.
  - 원본: agents/todo_creation/schemas.py:112 SplitResult / :16 TaskCandidate
후보 1(중국어 차단): title/tags 문자열 필드에 '허용 character class' pattern 을
  걸어 디코딩 단계에서 한자(CJK)가 애초에 나오지 못하게 한다.

이 모듈은 GPU·모델 없이도 import/검증 가능(순수 파이썬). run.py 만 vLLM 필요.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# --- 허용 character class (positive allowlist) -------------------------------
# 한글 음절/자모 + ASCII 영숫자 + 공백 + 제목/태그에 흔한 문장부호만 허용.
# 한자·가나·기타 CJK 는 '허용 목록에 없으므로' 디코딩 시 생성 불가.
_TITLE_BODY = r"가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9 ()·,.~/\-"
_TAG_BODY = r"가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9"

TITLE_PATTERN = rf"[{_TITLE_BODY}]{{1,20}}"
TAG_PATTERN = rf"[{_TAG_BODY}]{{1,20}}"
DATE_PATTERN = r"\d{4}-\d{2}-\d{2}"  # 후보 3 미리보기: year corruption 방지

# --- CJK(한자·가나) 탐지 — 측정용 -------------------------------------------
# Han(통합 U+4E00–9FFF / 확장A U+3400–4DBF / 호환 U+F900–FAFF)
# + 히라가나·가타카나(U+3040–30FF) + 주음부호(U+3100–312F).
# 한글 음절(U+AC00–D7A3)은 제외. literal CJK 문자를 소스에 쓰면 오타로 범위가
# 한글을 삼킬 수 있어(예: 豈=U+8C48≠U+F900) 코드포인트 정수 범위로 구성한다.
_CJK_RANGES = (
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # Ext A
    (0xF900, 0xFAFF),   # Compatibility Ideographs
    (0x3040, 0x30FF),   # Hiragana + Katakana
    (0x3100, 0x312F),   # Bopomofo
)
_CJK_RE = re.compile(
    "[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _CJK_RANGES) + "]"
)


def contains_cjk(text: str) -> bool:
    """문자열에 한자/가나 등 비한국어 CJK 문자가 있으면 True."""
    return bool(_CJK_RE.search(text))


# --- 제약 스키마 (Pydantic) --------------------------------------------------
# pattern 이 model_json_schema() 에 그대로 실려 vLLM(json) / outlines 양쪽이
# 같은 단일 소스를 쓴다.
Title = Annotated[str, Field(pattern=rf"^{TITLE_PATTERN}$", max_length=20)]
Tag = Annotated[str, Field(pattern=rf"^{TAG_PATTERN}$", max_length=20)]
DueDate = Annotated[str, Field(pattern=rf"^{DATE_PATTERN}$")]


class ConstrainedTask(BaseModel):
    title: Title
    due_date: DueDate
    tags: Annotated[list[Tag], Field(min_length=1, max_length=3)]


class ConstrainedSplit(BaseModel):
    """SplitResult 의 제약 버전. tasks 는 0~20개(out_of_scope 면 빈 배열)."""

    intent: Literal["plan", "out_of_scope"]
    tasks: Annotated[list[ConstrainedTask], Field(max_length=20)] = []


def split_json_schema() -> dict:
    """vLLM StructuredOutputsParams(json=...) 에 넣을 JSON Schema."""
    return ConstrainedSplit.model_json_schema()
