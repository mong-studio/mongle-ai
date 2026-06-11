import json
from pathlib import Path

from sft_pipeline.build.build_ipe_postcheck_hardening_sft import build_samples
from sft_pipeline.build.filter_dataset_by_kind import filter_by_kind
from sft_pipeline.build.validate_dataset import validate_samples
from sft_pipeline.train.postcheck import assistant_kind


def _info():
    return {
        "exam_code": "information_processing_engineer",
        "name": "정보처리기사",
    }


def _write(tmp_path: Path, name: str, samples: list[dict]) -> Path:
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(sample, ensure_ascii=False) for sample in samples) + "\n",
        encoding="utf-8",
    )
    return path


def test_postcheck_hardening_samples_validate(tmp_path):
    samples = build_samples(_info(), today="2026-06-09", plan_total=8, followup_total=4)
    report = validate_samples(_write(tmp_path, "postcheck_hardening.jsonl", samples))

    assert report["ok"] == 12
    assert report["errors"] == []
    assert [assistant_kind(sample["messages"][-1]["content"]) for sample in samples].count("plan") == 8
    assert [assistant_kind(sample["messages"][-1]["content"]) for sample in samples].count("follow_up") == 4


def test_filter_dataset_by_kind_splits_plan_and_followup():
    samples = build_samples(_info(), today="2026-06-09", plan_total=2, followup_total=2)

    plans = filter_by_kind(samples, {"plan"})
    followups = filter_by_kind(samples, {"follow_up"})

    assert len(plans) == 2
    assert len(followups) == 2
    assert {assistant_kind(sample["messages"][-1]["content"]) for sample in plans} == {"plan"}
    assert {assistant_kind(sample["messages"][-1]["content"]) for sample in followups} == {"follow_up"}
