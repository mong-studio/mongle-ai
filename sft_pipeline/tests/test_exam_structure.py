from sft_pipeline.build.exam_synth import EXAM_TYPES
from sft_pipeline.structure.exam_structure import (
    concreteness_ratio,
    load_exam_structures,
    structure_for,
)


def test_all_exam_types_have_structure():
    """합성 대상 시험 전부에 큐레이션된 구조(출처·sections·keywords)가 있는지 확인."""
    structures = load_exam_structures()
    for exam_type in EXAM_TYPES:
        assert exam_type in structures, f"{exam_type} 구조 누락"
        s = structures[exam_type]
        assert s["source"], f"{exam_type} 출처 누락"
        assert s["sections"], f"{exam_type} sections 비어 있음"
        assert s["keywords"], f"{exam_type} keywords 비어 있음"


def test_structure_for_unknown_returns_none():
    """미등록 시험은 None (추정 금지 - exam_types.py 와 동일 원칙)."""
    assert structure_for("정체불명시험") is None


def test_concreteness_ratio_counts_keyword_titles():
    """구조 키워드를 포함한 title 비율을 계산하는지 확인."""
    titles = ["RC Part5 문법 오답 정리", "약점 보완", "LC 쉐도잉 훈련", "기출 1회독"]
    assert concreteness_ratio(titles, "토익") == 0.5


def test_concreteness_ratio_normalizes_spacing_and_case():
    """공백·대소문자 차이를 무시하고 매칭하는지 확인."""
    assert concreteness_ratio(["rc part5 집중"], "토익") == 1.0
    assert concreteness_ratio(["소프트웨어설계 기출 풀이"], "정보처리기사_필기") == 1.0


def test_concreteness_ratio_empty_or_unknown_is_zero():
    """빈 목록·미등록 시험은 0.0 (게이트에서 안전하게 reject 방향)."""
    assert concreteness_ratio([], "토익") == 0.0
    assert concreteness_ratio(["아무 제목"], "정체불명시험") == 0.0
