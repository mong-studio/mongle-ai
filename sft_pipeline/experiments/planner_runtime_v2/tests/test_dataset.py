from collections import Counter
from pathlib import Path

from sft_pipeline.build.lib.validate_dataset import validate_samples
from sft_pipeline.experiments.planner_runtime_v2.build_dataset import build_samples
from sft_pipeline.experiments.planner_runtime_v2.evaluate import (
    _content_text,
    _has_english_leak,
)
from sft_pipeline.io_utils import write_jsonl


def test_runtime_v2_builds_300_valid_samples(tmp_path: Path):
    samples = build_samples()
    assert len(samples) == 300
    assert len({tuple(m["content"] for m in s["messages"]) for s in samples}) == 300

    domains = Counter(s["meta"]["domain"] for s in samples)
    assert domains["project"] >= 100
    assert domains["event"] == 50
    assert domains["exam"] == 60
    assert domains["routine"] == 40
    assert domains["lifestyle"] == 40

    output = tmp_path / "runtime-v2.jsonl"
    write_jsonl(samples, output)
    report = validate_samples(output)
    assert report == {"ok": 300, "errors": []}


def test_committed_runtime_v2_dataset_matches_generator():
    import json

    path = Path(
        "sft_pipeline/experiments/planner_runtime_v2/data/"
        "planner_runtime_v2_gold_300.jsonl"
    )
    committed = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert committed == build_samples()


def test_language_gate_allows_exam_acronyms_only():
    assert not _has_english_leak("SQLD와 JLPT 시험 준비")
    assert _has_english_leak("prepare interview schedule")


def test_language_gate_ignores_json_keys_but_checks_values():
    assert not _has_english_leak(_content_text('{"summary_text":"준비해요"}'))
    assert _has_english_leak(_content_text('{"summary_text":"prepare schedule"}'))
