import csv
from pathlib import Path

from sft_pipeline.structure.run_structure import read_raw_cases, write_structured

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "raw_cases_sample.csv"


def test_read_skips_comment_rows():
    """raw_cases CSV를 읽을 때 주석(#) 행은 건너뛰고 실제 12건만 읽는지 확인."""
    rows = read_raw_cases(SAMPLE)
    assert len(rows) == 12
    assert all(not r["source_url"].startswith("#") for r in rows)


def test_write_structured_roundtrip(tmp_path):
    """읽은 행을 구조화해 CSV로 쓰고 다시 읽으면 정규화 값(시험명·기간)과 불합격 사례가 보존되는지 확인."""
    rows = read_raw_cases(SAMPLE)
    out = tmp_path / "structured.csv"
    write_structured(rows, out)
    with open(out, encoding="utf-8") as f:
        result = list(csv.DictReader(f))
    assert len(result) == 12
    assert result[0]["exam_type"] == "정보처리기사_필기"
    assert result[0]["time_left_days"] == "7"
    # 불합격 사례 포함 확인
    assert any(r["result"] == "불합격" for r in result)
