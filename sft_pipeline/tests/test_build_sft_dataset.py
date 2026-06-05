import json
from pathlib import Path

from sft_pipeline.build.build_sft_dataset import build_samples, write_jsonl


def _structured_csv(tmp_path: Path) -> Path:
    import csv

    from sft_pipeline.structure.run_structure import STRUCTURED_COLUMNS

    path = tmp_path / "structured.csv"
    row = {c: "" for c in STRUCTURED_COLUMNS}
    row.update(
        source_url="https://example.com/case-1",
        exam_type="정보처리기사_필기",
        time_left="D-7",
        time_left_days="7",
        daily_hours="하루 4시간",
        daily_hours_value="4.0",
        start_level="비전공",
        goal="합격",
        actual_plan_summary="기출 3회독",
        result="합격",
    )
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STRUCTURED_COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    return path


def test_build_samples_messages_schema(tmp_path):
    """structured.csv → messages 통일 스키마(user→assistant 2턴)와 메타 필드가 채워지는지 확인."""
    samples = build_samples(_structured_csv(tmp_path))
    assert len(samples) == 1
    s = samples[0]
    assert set(s) == {"messages", "meta"}

    msgs = s["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert all(m["content"].strip() for m in msgs)
    # 시험 조건(input)이 user 메시지에, 계획 요약이 assistant 메시지에 담겨야 한다.
    assert "정보처리기사_필기" in msgs[0]["content"]
    assert "기출 3회독" in msgs[1]["content"]

    meta = s["meta"]
    assert meta["source_url"] == "https://example.com/case-1"
    assert meta["exam_type"] == "정보처리기사_필기"
    assert meta["result"] == "합격"
    assert meta["provenance"] == "exam-crawl"
    assert meta["turn_type"] == "single"
    assert "evidence_spans" in meta
    assert meta["rephrased_by"] == "template"


def test_write_jsonl(tmp_path):
    """build_samples 결과를 JSONL로 쓰면 한 줄당 한 샘플로 직렬화되는지 확인."""
    samples = build_samples(_structured_csv(tmp_path))
    out = tmp_path / "sft.jsonl"
    write_jsonl(samples, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded["meta"]["exam_type"] == "정보처리기사_필기"
    assert loaded["messages"][-1]["role"] == "assistant"


def test_malformed_numeric_meta_becomes_none(tmp_path):
    """숫자 메타(time_left_days·daily_hours_value)가 파싱 불가 문자열이면 None으로 안전 변환되는지 확인."""
    import csv

    from sft_pipeline.structure.run_structure import STRUCTURED_COLUMNS

    path = tmp_path / "structured.csv"
    row = {c: "" for c in STRUCTURED_COLUMNS}
    row.update(
        source_url="https://example.com/x",
        exam_type="토익",
        result="합격",
        time_left_days="abc",
        daily_hours_value="??",
        actual_plan_summary="계획",
    )
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STRUCTURED_COLUMNS)
        w.writeheader()
        w.writerow(row)
    samples = build_samples(path)
    assert samples[0]["meta"]["time_left_days"] is None
    assert samples[0]["meta"]["daily_hours"] is None
