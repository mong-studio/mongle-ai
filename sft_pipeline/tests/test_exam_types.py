from sft_pipeline.structure.exam_types import canonicalize_exam_type


def test_canonical_passthrough():
    """이미 정규 명칭이면 그대로 통과시키는지 확인."""
    assert canonicalize_exam_type("정보처리기사_필기") == "정보처리기사_필기"


def test_alias_match():
    """약칭·영문 별칭(정처기 필기, TOEIC, 한능검)이 정규 명칭으로 매핑되는지 확인."""
    assert canonicalize_exam_type("정처기 필기") == "정보처리기사_필기"
    assert canonicalize_exam_type("TOEIC") == "토익"
    assert canonicalize_exam_type("한능검") == "한국사능력검정시험"


def test_level_disambiguation():
    """급수가 다른 시험(컴활 1급/2급)을 각각 구분해 매핑하는지 확인."""
    assert canonicalize_exam_type("컴활 1급") == "컴활1급"
    assert canonicalize_exam_type("컴활 2급") == "컴활2급"


def test_language_exam_aliases():
    """어학 시험(오픽·토플·JLPT) 별칭이 정규 명칭으로 매핑되는지 확인."""
    assert canonicalize_exam_type("OPIc") == "오픽"
    assert canonicalize_exam_type("오픽") == "오픽"
    assert canonicalize_exam_type("TOEFL") == "토플"
    assert canonicalize_exam_type("토플 iBT") == "토플"
    assert canonicalize_exam_type("jlpt") == "JLPT"
    assert canonicalize_exam_type("일본어능력시험") == "JLPT"


def test_unknown_returns_none():
    """미등록 시험명·빈 문자열은 None을 반환하는지 확인."""
    assert canonicalize_exam_type("정체불명시험") is None
    assert canonicalize_exam_type("") is None


def test_partial_or_related_names_not_misclassified():
    """유사하지만 다른 시험(토익스피킹)·급수 미상(컴활)은 오분류하지 않는지 확인."""
    assert canonicalize_exam_type("토익스피킹") is None
    assert canonicalize_exam_type("컴활") is None
