from __future__ import annotations

import pytest

from agents.todo_creation.title_normalizer import normalize_title


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("오늘 가서 랭그래프 실습 과제를 끝내고", "랭그래프 실습 과제 완료"),
        ("프레젠테이션 데모를 만들거야", "프레젠테이션 데모 제작"),
        ("코드를 짜고", "코드 작성"),
        ("이메일을 보내야지", "이메일 발송"),
        ("버그를 고치려고", "버그 수정"),
        # HADA 경로: 동사 어미만 제거, 명사 어근 유지
        ("오늘 집 가서 데이터 전처리 파이프라인을 구축하고", "데이터 전처리 파이프라인 구축"),
        ("데이터 전처리 형식을 통일할거야", "데이터 전처리 형식 통일"),
        ("캐릭터 생성 노드 리팩토링하고", "캐릭터 생성 노드 리팩토링"),
        ("내일 오전에 발표하려고", "발표"),
        ("문서 작성해야지", "문서 작성"),
        # passthrough / leading-only
        ("회의 준비", "회의 준비"),
        ("코테", "코테"),
        ("어제 일", "일"),
    ],
)
def test_normalize_title_known_cases(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_normalize_title_unmapped_verb_falls_back_to_head() -> None:
    # 매핑 사전에 없는 동사는 head 명사만 남긴다 (보수적 fallback).
    # '먹' 은 _VERB_NOUN_MAP 미등록 → '점심' 만 보존.
    assert normalize_title("점심을 먹고") == "점심"


def test_normalize_title_respects_max_len() -> None:
    assert len(normalize_title("x" * 200, max_len=80)) == 80


def test_normalize_title_preserves_clean_input() -> None:
    assert normalize_title("랭그래프 실습 과제") == "랭그래프 실습 과제"
