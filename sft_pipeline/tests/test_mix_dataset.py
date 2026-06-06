import json
from pathlib import Path

from sft_pipeline.build.mix_dataset import mix
from sft_pipeline.build.validate_dataset import validate_samples


def _plan(events_due="2026-06-08"):
    return json.dumps(
        {
            "summary_text": "기출 위주 반복 전략이에요.",
            "todos": [{"title": "핵심 개념 훑기", "due_date": "2026-06-06", "tags": ["공부"]}],
            "calendar_events": [
                {"title": "오답 정리·반복", "due_date": events_due, "tags": ["공부"]}
            ],
        },
        ensure_ascii=False,
    )


def _exam():
    return {
        "messages": [
            {"role": "user", "content": "시험 계획 짜줘.\n\n시험: 토익 / D-7 / 기준일(오늘): 2026-06-06"},
            {"role": "assistant", "content": _plan()},
        ],
        "meta": {
            "provenance": "exam-crawl",
            "source_url": "https://e.com/1",
            "exam_type": "토익",
            "result": "합격",
            "today": "2026-06-06",
            "time_left_days": 7,
        },
    }


def _daily():
    return {
        "messages": [
            {"role": "user", "content": "마트에서 장보기 계획 짜줘. (기준일: 2026-06-06)"},
            {"role": "assistant", "content": _plan()},
        ],
        "meta": {
            "provenance": "daily-latte",
            "source_id": "1",
            "license": "MIT",
            "today": "2026-06-06",
        },
    }


def test_public_excludes_exam():
    """release=public 이면 저작권 위험한 exam-crawl 을 모두 제외한다."""
    out = mix([_exam(), _daily()], release="public")
    assert len(out) == 1
    assert out[0]["meta"]["provenance"] == "daily-latte"


def test_internal_includes_all():
    """release=internal 이면 시험+일상 모두 포함한다."""
    out = mix([_exam(), _daily()], release="internal")
    assert len(out) == 2
    provs = {s["meta"]["provenance"] for s in out}
    assert provs == {"exam-crawl", "daily-latte"}


def test_public_excludes_unknown_provenance():
    """fail-closed: 허용목록(daily-latte)에 없는 출처(오타/누락 포함)는 public에서 제외."""
    mystery = {"messages": _daily()["messages"], "meta": {"provenance": "mystery"}}
    no_prov = {"messages": _daily()["messages"], "meta": {}}
    out = mix([_daily(), mystery, no_prov], release="public")
    assert len(out) == 1
    assert out[0]["meta"]["provenance"] == "daily-latte"


def test_mixed_output_validates(tmp_path):
    """믹스 결과가 통일 validate 스키마를 통과한다."""
    out = mix([_exam(), _daily()], release="internal")
    path: Path = tmp_path / "ds.jsonl"
    path.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in out) + "\n", encoding="utf-8")
    report = validate_samples(path)
    assert report["ok"] == 2, report["errors"]
