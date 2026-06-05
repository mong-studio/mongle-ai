import json
from pathlib import Path

from sft_pipeline.build.mix_dataset import mix
from sft_pipeline.build.validate_dataset import validate_samples


def _exam():
    return {
        "messages": [
            {"role": "user", "content": "시험 계획 짜줘.\n\n시험: 토익 / D-7"},
            {"role": "assistant", "content": "[토익 · D-7 준비 플랜] 매일 모의고사 1회분 풀기."},
        ],
        "meta": {"provenance": "exam-crawl", "source_url": "https://e.com/1", "exam_type": "토익", "result": "합격"},
    }


def _daily():
    return {
        "messages": [
            {"role": "user", "content": "마트에서 장보기 계획 짜줘."},
            {"role": "assistant", "content": "주말 아침에 마트 들르는 걸 추천해요. 한가해서 좋아요."},
        ],
        "meta": {"provenance": "daily-latte", "source_id": "1", "license": "MIT"},
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


def test_mixed_output_validates(tmp_path):
    """믹스 결과가 통일 validate 스키마를 통과한다."""
    out = mix([_exam(), _daily()], release="internal")
    path: Path = tmp_path / "ds.jsonl"
    path.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in out) + "\n", encoding="utf-8")
    report = validate_samples(path)
    assert report["ok"] == 2, report["errors"]
