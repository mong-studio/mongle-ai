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
    """시험준비 단일턴(user→assistant) 샘플."""
    return {
        "messages": [
            {
                "role": "user",
                "content": "다음 조건에 맞는 단기 시험 준비 계획을 세워줘.\n\n시험: 토익 / 남은 기간: D-7",
            },
            {
                "role": "assistant",
                "content": "[토익 · D-7 준비 플랜]\n추천 학습 흐름: 매일 모의고사 1회분",
            },
        ],
        "meta": {
            "provenance": "exam-crawl",
            "source_url": "https://example.com/1",
            "exam_type": "토익",
            "result": "합격",
        },
    }


def _good_daily():
    """일상 멀티턴(MS-LaTTE 유래) 샘플 - exam 필드 없이 provenance만 다르다."""
    return {
        "messages": [
            {"role": "user", "content": "이번 주에 장보기랑 운동 계획 좀 같이 짜줘."},
            {"role": "assistant", "content": "좋아요. 장보기는 주말 오전, 운동은 평일 저녁으로 배치해볼게요."},
            {"role": "user", "content": "운동은 화목만 가능해."},
            {"role": "assistant", "content": "그럼 화·목 저녁 7시로 고정하고 장보기는 토요일 오전에 넣을게요."},
        ],
        "meta": {"provenance": "daily-latte", "source_id": "latte-000123", "license": "MIT"},
    }


def test_valid_exam_sample_passes(tmp_path):
    """messages 스키마를 갖춘 정상 시험 샘플은 통과(ok=1)하고 오류가 없는지 확인."""
    report = validate_samples(_write(tmp_path, [_good()]))
    assert report["ok"] == 1
    assert report["errors"] == []


def test_valid_daily_sample_passes(tmp_path):
    """exam_type/result 없는 일상 멀티턴 샘플도 통일 스키마에서 통과하는지 확인."""
    report = validate_samples(_write(tmp_path, [_good_daily()]))
    assert report["ok"] == 1
    assert report["errors"] == []


def test_missing_messages_flagged(tmp_path):
    """필수 키(messages)가 빠지면 오류로 보고하는지 확인."""
    bad = _good()
    del bad["messages"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("messages" in e for e in report["errors"])


def test_last_must_be_assistant(tmp_path):
    """대화의 마지막 턴이 assistant가 아니면 오류로 잡는지 확인."""
    bad = _good_daily()
    bad["messages"] = bad["messages"][:-1]  # 마지막 assistant 제거 → user로 끝남
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("last" in e or "assistant" in e for e in report["errors"])


def test_empty_content_flagged(tmp_path):
    """빈 content 메시지는 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = "   "
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("empty" in e for e in report["errors"])


def test_raw_copy_flagged(tmp_path):
    """assistant가 직전 user 메시지를 그대로 복붙하면 raw_copy 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = bad["messages"][0]["content"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("raw_copy" in e for e in report["errors"])


def test_exam_provenance_missing_meta_flagged(tmp_path):
    """provenance=exam-crawl인데 exam_type이 없으면 오류로 잡는지 확인."""
    bad = _good()
    del bad["meta"]["exam_type"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("exam_type" in e for e in report["errors"])
