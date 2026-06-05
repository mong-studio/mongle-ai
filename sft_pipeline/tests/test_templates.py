from sft_pipeline.build.templates import build_input, build_instruction, build_output


CASE = {
    "exam_type": "정보처리기사_필기",
    "time_left": "D-7",
    "time_left_days": "7",
    "daily_hours": "하루 4시간",
    "start_level": "비전공 노베이스",
    "goal": "과목당 60점 합격",
    "special_notes": "직장 병행",
    "actual_plan_summary": "기출 5개년 3회독 후 오답 정리",
    "result": "합격",
}


def test_build_input_contains_fields():
    """input 텍스트에 시험명·남은 기간·학습시간 등 핵심 필드가 포함되는지 확인."""
    text = build_input(CASE)
    assert "정보처리기사_필기" in text
    assert "D-7" in text
    assert "하루 4시간" in text


def test_build_instruction_nonempty():
    """instruction 문자열이 비어 있지 않은지 확인."""
    assert len(build_instruction(CASE)) > 0


def test_build_instruction_varies_across_indices():
    """instruction은 인덱스에 따라 2개 이상 서로 다른 표현으로 분산된다 (SFT 다양성)."""
    seen = {build_instruction(CASE, i) for i in range(10)}
    assert len(seen) > 1


def test_build_instruction_deterministic_per_index():
    """같은 인덱스는 항상 같은 instruction (데이터셋 재현성)."""
    assert build_instruction(CASE, 3) == build_instruction(CASE, 3)


def test_build_output_reframes_not_rawcopy():
    """output이 계획 요약을 반영하되 원문 복붙이 아니라 재구성된 형태인지 확인."""
    out = build_output(CASE)
    assert "기출 5개년 3회독" in out  # 계획 요약 반영
    assert out != CASE["actual_plan_summary"]  # 단순 복붙 아님
    assert "정보처리기사_필기" in out
