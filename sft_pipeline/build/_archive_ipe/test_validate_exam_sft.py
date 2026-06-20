import json
from pathlib import Path

from sft_pipeline.build._archive_ipe.validate_exam_sft import validate_samples


def _write(tmp_path: Path, samples: list[dict]) -> Path:
    path = tmp_path / "exam.jsonl"
    path.write_text(
        "\n".join(json.dumps(sample, ensure_ascii=False) for sample in samples) + "\n",
        encoding="utf-8",
    )
    return path


def _assistant_plan(summary_text: str | None = None) -> str:
    return json.dumps(
        {
            "kind": "plan",
            "title": "정처기 필기 3일 준비",
            "deadline": "2026-06-12",
            "assumptions": [],
            "phases": [
                {
                    "phase": "기출 집중",
                    "due_date": "2026-06-10",
                    "tasks": [
                        {
                            "title": "필기 5과목 기출 풀이",
                            "due_date": "2026-06-10",
                            "priority": "high",
                            "tags": ["정처기", "필기"],
                        }
                    ],
                }
            ],
            "calendar_events": [
                {"title": "정보처리기사 필기", "due_date": "2026-06-12", "tags": ["시험"]}
            ],
            "summary_text": summary_text
            or "정보처리기사 필기는 소프트웨어설계, 소프트웨어개발, 데이터베이스구축, "
            "프로그래밍언어활용, 정보시스템구축관리 5과목이며 과목당 40점 이상, "
            "평균 60점 이상이 합격 기준입니다.",
        },
        ensure_ascii=False,
    )


def _good() -> dict:
    return {
        "messages": [
            {"role": "system", "content": "출력은 JSON만 사용한다."},
            {"role": "user", "content": "정보처리기사 필기 3일 준비 계획을 세워줘."},
            {"role": "assistant", "content": _assistant_plan()},
        ],
        "meta": {
            "id": "ipe-test-1",
            "today": "2026-06-09",
            "provenance": "exam-crawl",
            "source_url": "https://example.com/ipe",
            "source_batch": "exam_information_processing_engineer_sft",
            "exam_type": "정보처리기사 필기",
            "exam_part": "written",
            "result": "합격",
            "time_left_days": 3,
            "study_process_summary": "기출 중심으로 3일 압축 학습했다.",
            "review_summary": "과락 기준을 의식하며 약점 과목을 반복했다.",
        },
    }


def test_valid_ipe_exam_sft_passes(tmp_path):
    report = validate_samples(_write(tmp_path, [_good()]))
    assert report["ok"] == 1
    assert report["errors"] == []
    assert report["by_part"] == {"written": 1}


def test_missing_official_terms_flagged(tmp_path):
    bad = _good()
    bad["messages"][-1]["content"] = _assistant_plan("기출을 반복해서 풀어 합격 기준을 넘긴다.")
    report = validate_samples(_write(tmp_path, [bad]))
    assert report["ok"] == 0
    assert any("official terms" in error for error in report["errors"])


def test_duplicate_meta_id_flagged(tmp_path):
    first = _good()
    second = _good()
    second["messages"][1]["content"] = "정보처리기사 필기 5일 준비 계획을 세워줘."
    report = validate_samples(_write(tmp_path, [first, second]))
    assert report["ok"] == 1
    assert any("duplicate meta.id" in error for error in report["errors"])
