import json
from datetime import date
from pathlib import Path

from sft_pipeline.build.build_ipe_runtime_hardening_sft import PROVENANCE, build_samples
from sft_pipeline.build.plan_schemas import check_plan_consistency, parse_plan
from sft_pipeline.build.validate_dataset import validate_samples


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


def test_build_runtime_hardening_samples_are_valid_sft(tmp_path):
    samples = build_samples(_info(), today="2026-06-09", total=10)
    path = _write(tmp_path, "hardening.jsonl", samples)
    report = validate_samples(path)

    assert report["ok"] == 10
    assert report["errors"] == []
    assert {sample["meta"]["provenance"] for sample in samples} == {PROVENANCE}


def test_runtime_hardening_targets_postcheck_failures():
    samples = build_samples(_info(), today="2026-06-09", total=20)
    user_messages = {sample["messages"][1]["content"] for sample in samples}

    assert len(user_messages) == len(samples)
    for sample in samples:
        plan = parse_plan(sample["messages"][-1]["content"])
        assert check_plan_consistency(plan, today=date(2026, 6, 9), horizon_days=31) == []
        for task in [*plan.todos, *plan.calendar_events]:
            assert len(task.title) <= 20
            assert task.due_date.isoformat() == str(task.due_date)
            assert all("编" not in tag and "复" not in tag for tag in task.tags)
