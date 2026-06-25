import json
from pathlib import Path

from sft_pipeline.build.lib.mix_dataset import interleave, mix
from sft_pipeline.build.lib.validate_dataset import validate_samples


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


def _distractor():
    return {
        "messages": [
            {"role": "user", "content": "고마워"},
            {"role": "assistant", "content": "도움이 됐다면 다행이야. 더 말해줘."},
        ],
        "meta": {
            "provenance": "distractor",
            "distractor_type": "thanks_chitchat",
            "is_distractor": True,
            "source_id": "1",
        },
    }


def test_mixed_output_validates(tmp_path):
    """믹스 결과가 통일 validate 스키마를 통과한다."""
    out = mix([_exam(), _daily()], release="internal")
    path: Path = tmp_path / "ds.jsonl"
    path.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in out) + "\n", encoding="utf-8")
    report = validate_samples(path)
    assert report["ok"] == 2, report["errors"]


def test_public_includes_distractor():
    """distractor 는 우리 IP 라 공개판에도 포함된다(화이트리스트 추가)."""
    out = mix([_daily(), _distractor()], release="public")
    provs = sorted(s["meta"]["provenance"] for s in out)
    assert provs == ["daily-latte", "distractor"]


def _exam_synth():
    return {
        "messages": _daily()["messages"],
        "meta": {"provenance": "exam-synth", "exam_type": "토익", "time_left_days": 14, "today": "2026-06-06"},
    }


def test_public_includes_exam_synth():
    """exam-synth(우리 합성)는 공개판 포함, exam-crawl은 제외."""
    out = mix([_daily(), _exam_synth(), _exam()], release="public")
    provs = sorted(s["meta"]["provenance"] for s in out)
    assert provs == ["daily-latte", "exam-synth"]


def test_public_includes_planner_runtime():
    sample = _daily()
    sample["meta"]["provenance"] = "planner-runtime"

    out = mix([sample], release="public")

    assert out == [sample]


def test_distractor_mix_validates(tmp_path):
    """plan(daily) + distractor 혼합이 통일 validate 를 통과한다(2층 분기 확인)."""
    out = mix([_daily(), _distractor()], release="internal")
    path: Path = tmp_path / "ds.jsonl"
    path.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in out) + "\n", encoding="utf-8")
    report = validate_samples(path)
    assert report["ok"] == 2, report["errors"]


def test_interleave_spreads_extra_and_preserves_order():
    base = [{"i": i, "k": "b"} for i in range(6)]
    extra = [{"i": i, "k": "e"} for i in range(2)]
    out = interleave(base, extra)
    assert len(out) == 8
    assert [x["i"] for x in out if x["k"] == "b"] == [0, 1, 2, 3, 4, 5]  # base 순서 보존
    assert sum(1 for x in out if x["k"] == "e") == 2
    epos = [idx for idx, x in enumerate(out) if x["k"] == "e"]
    assert epos[0] < 4  # 끝에 몰리지 않고 앞쪽부터 분산
    assert interleave(base, extra) == out  # 결정론적


def test_interleave_handles_empty():
    assert interleave([], [{"a": 1}]) == [{"a": 1}]
    assert interleave([{"a": 1}], []) == [{"a": 1}]
