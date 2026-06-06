import json
from pathlib import Path

from sft_pipeline.build.validate_dataset import validate_samples


def _write(tmp_path: Path, samples: list[dict]) -> Path:
    path = tmp_path / "ds.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return path


def _good():
    return {
        "instruction": "다음 조건에 맞는 단기 시험 준비 계획을 세워줘.",
        "input": "시험: 토익 / 남은 기간: D-7",
        "output": "[토익 · D-7 준비 플랜]\n추천 학습 흐름: 매일 모의고사 1회분",
        "meta": {"source_url": "https://example.com/1", "exam_type": "토익", "result": "합격"},
    }


def test_valid_sample_passes(tmp_path):
    """필수 키를 모두 갖춘 정상 샘플은 통과(ok=1)하고 오류가 없는지 확인."""
    report = validate_samples(_write(tmp_path, [_good()]))
    assert report["ok"] == 1
    assert report["errors"] == []


def test_missing_key_flagged(tmp_path):
    """필수 키(output)가 빠지면 오류로 보고하는지 확인."""
    bad = _good()
    del bad["output"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("output" in e for e in report["errors"])


def test_raw_copy_flagged(tmp_path):
    """output이 input을 그대로 복붙한 경우 raw_copy 오류로 잡아내는지 확인."""
    bad = _good()
    bad["output"] = bad["input"]  # input 그대로 복붙
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("raw_copy" in e for e in report["errors"])
