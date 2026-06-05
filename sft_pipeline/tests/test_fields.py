from sft_pipeline.structure.fields import RAW_COLUMNS, structure_row


def _row(**overrides):
    base = {c: "" for c in RAW_COLUMNS}
    base.update(
        source_url="https://example.com/case-1",
        exam_type="정처기 필기",
        time_left="D-7",
        daily_hours="하루 4시간",
        start_level="비전공 노베이스",
        goal="과목당 60점 합격",
        special_notes="직장 병행",
        actual_plan_summary="기출 3회독 + 오답정리",
        result="합격",
    )
    base.update(overrides)
    return base


def test_structure_row_happy_path():
    """정상 입력 행을 구조화하면 시험명 정규화·기간/시간 파싱·결과가 채워지고 검수 플래그가 없는지 확인."""
    case = structure_row(_row())
    assert case.exam_type == "정보처리기사_필기"
    assert case.time_left_days == 7
    assert case.daily_hours_value == 4.0
    assert case.result == "합격"
    assert case.review_flags == []


def test_unknown_exam_type_flagged():
    """매핑 불가 시험명은 빈 값으로 두고 exam_type_unmapped 플래그를 다는지 확인."""
    case = structure_row(_row(exam_type="정체불명"))
    assert case.exam_type == ""
    assert "exam_type_unmapped" in case.review_flags


def test_missing_time_left_flagged_not_guessed():
    """남은 기간이 비면 추측하지 않고 None + time_left_missing 플래그로 처리하는지 확인."""
    case = structure_row(_row(time_left=""))
    assert case.time_left_days is None
    assert "time_left_missing" in case.review_flags


def test_invalid_result_normalized_to_unknown():
    """판정 불가 결과 값은 '미상'으로 정규화하고 result_unknown 플래그를 다는지 확인."""
    case = structure_row(_row(result="음.."))
    assert case.result == "미상"
    assert "result_unknown" in case.review_flags


def test_missing_daily_hours_flagged():
    """하루 학습시간이 비면 None + daily_hours_missing 플래그로 처리하는지 확인."""
    case = structure_row(_row(daily_hours=""))
    assert case.daily_hours_value is None
    assert "daily_hours_missing" in case.review_flags
