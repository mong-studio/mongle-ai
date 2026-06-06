import json
from datetime import date
from pathlib import Path

from sft_pipeline.build.build_sft_dataset import build_samples, write_jsonl
from sft_pipeline.build.plan_schemas import check_plan_consistency, parse_plan

TODAY = date(2026, 6, 6)


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
    samples = build_samples(_structured_csv(tmp_path), today=TODAY)
    assert len(samples) == 1
    s = samples[0]
    assert set(s) == {"messages", "meta"}

    msgs = s["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert all(m["content"].strip() for m in msgs)
    # 시험 조건(input)과 날짜 산술 앵커(기준일)가 user 메시지에 담겨야 한다.
    assert "정보처리기사_필기" in msgs[0]["content"]
    assert "기준일" in msgs[0]["content"]
    assert "2026-06-06" in msgs[0]["content"]
    # 크롤 전략(actual_plan_summary)이 assistant 출력에 그라운딩되어야 한다.
    assert "기출 3회독" in msgs[1]["content"]

    meta = s["meta"]
    assert meta["source_url"] == "https://example.com/case-1"
    assert meta["exam_type"] == "정보처리기사_필기"
    assert meta["result"] == "합격"
    assert meta["provenance"] == "exam-crawl"
    assert meta["turn_type"] == "single"
    assert meta["today"] == "2026-06-06"
    assert "evidence_spans" in meta
    assert meta["rephrased_by"] == "template"


def test_assistant_output_is_consistent_structured_plan(tmp_path):
    """assistant 출력이 런타임 스키마(JSON) 파싱·정합성 검증을 통과해야 한다."""
    samples = build_samples(_structured_csv(tmp_path), today=TODAY)
    plan = parse_plan(samples[0]["messages"][-1]["content"])

    assert check_plan_consistency(plan, today=TODAY, horizon_days=7) == []
    # C5 분기: 오늘 할 일은 todos, 미래는 calendar_events.
    assert plan.todos and all(t.due_date == TODAY for t in plan.todos)
    assert plan.calendar_events and all(t.due_date > TODAY for t in plan.calendar_events)
    # 전략 내러티브는 summary_text 에 담긴다.
    assert plan.summary_text and "기출 3회독" in plan.summary_text


def test_short_horizon_still_consistent(tmp_path):
    """D-1 같은 짧은 기간도 빈 플랜 없이 정합성을 지켜야 한다."""
    import csv

    from sft_pipeline.structure.run_structure import STRUCTURED_COLUMNS

    path = tmp_path / "structured.csv"
    row = {c: "" for c in STRUCTURED_COLUMNS}
    row.update(
        source_url="https://example.com/x",
        exam_type="토익",
        result="합격",
        time_left="D-1",
        time_left_days="1",
        actual_plan_summary="모의고사 복습",
    )
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STRUCTURED_COLUMNS)
        w.writeheader()
        w.writerow(row)
    samples = build_samples(path, today=TODAY)
    plan = parse_plan(samples[0]["messages"][-1]["content"])
    assert check_plan_consistency(plan, today=TODAY, horizon_days=1) == []
    assert plan.todos  # 오늘 항목은 반드시 존재


def test_write_jsonl(tmp_path):
    """build_samples 결과를 JSONL로 쓰면 한 줄당 한 샘플로 직렬화되는지 확인."""
    samples = build_samples(_structured_csv(tmp_path), today=TODAY)
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
    samples = build_samples(path, today=TODAY)
    assert samples[0]["meta"]["time_left_days"] is None
    assert samples[0]["meta"]["daily_hours"] is None
    # 기간 미상이어도 구조화 플랜은 생성된다(기본 7일).
    plan = parse_plan(samples[0]["messages"][-1]["content"])
    assert check_plan_consistency(plan, today=TODAY, horizon_days=None) == []
