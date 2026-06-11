import json
from pathlib import Path

from sft_pipeline.build.build_ipe_followup_sft import PROVENANCE, build_samples
from sft_pipeline.build.combine_ipe_training_sft import combine
from sft_pipeline.build.validate_dataset import validate_samples


def _info():
    return {
        "exam_code": "information_processing_engineer",
        "name": "정보처리기사",
        "official_sources": [{"url": "https://q-net.example/ipe"}],
    }


def _write(tmp_path: Path, name: str, samples: list[dict]) -> Path:
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(sample, ensure_ascii=False) for sample in samples) + "\n",
        encoding="utf-8",
    )
    return path


def test_build_followup_samples_are_valid_sft(tmp_path):
    samples = build_samples(_info(), today="2026-06-09", total=10)
    path = _write(tmp_path, "followup.jsonl", samples)
    report = validate_samples(path)
    assert report["ok"] == 10
    assert report["errors"] == []
    assert {sample["meta"]["provenance"] for sample in samples} == {PROVENANCE}
    assert {
        json.loads(sample["messages"][-1]["content"])["kind"] for sample in samples
    } == {"follow_up"}


def test_combine_training_sft_counts_provenance(tmp_path):
    plan = {
        "messages": [
            {"role": "user", "content": "오늘 공부 계획 세워줘. 기준일: 2026-06-09"},
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "summary_text": "오늘은 합격 기준을 확인합니다.",
                        "todos": [{"title": "합격 기준 확인", "due_date": "2026-06-09", "tags": []}],
                        "calendar_events": [],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "meta": {
            "id": "plan-1",
            "provenance": "exam-crawl",
            "source_url": "https://example.com",
            "exam_type": "정보처리기사 필기",
            "result": "합격",
            "today": "2026-06-09",
            "time_left_days": 1,
        },
    }
    followups = build_samples(_info(), today="2026-06-09", total=2)
    samples, by_provenance, duplicates = combine(
        [
            _write(tmp_path, "plan.jsonl", [plan]),
            _write(tmp_path, "followup.jsonl", followups),
        ]
    )
    assert len(samples) == 3
    assert by_provenance == {"exam-crawl": 1, PROVENANCE: 2}
    assert duplicates == []
