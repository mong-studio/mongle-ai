"""정보처리기사 follow_up SFT 샘플을 결정론적으로 생성한다.

크롤 기반 plan 데이터는 정보가 충분한 요청에 답하는 패턴을 강화한다. 이 파일은
시험일·필기/실기·가용시간·현재 수준처럼 핵심 슬롯이 빠진 요청에 대해 모델이
바로 계획을 만들지 않고 추가 질문을 하도록 학습하는 synthetic 배치를 만든다.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sft_pipeline.build.lib.prompts import runtime_system_prompt
from sft_pipeline.io_utils import write_jsonl


DEFAULT_INFO = Path("sft_pipeline/data/exam_info/information_processing_engineer.json")
DEFAULT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_followup_sft.jsonl")
DEFAULT_TODAY = "2026-06-09"
PROVENANCE = "exam-follow-up-synth"


@dataclass(frozen=True)
class FollowUpCase:
    case_id: str
    user: str
    question: str
    missing_aspects: tuple[str, ...]
    tags: tuple[str, ...]


BASE_CASES: tuple[FollowUpCase, ...] = (
    FollowUpCase(
        "missing-part-date",
        "정보처리기사 준비 계획 세워줘.",
        "필기와 실기 중 어떤 시험을 준비 중이고, 시험일은 언제인가요?",
        ("exam_part", "exam_date"),
        ("시험구분", "시험일"),
    ),
    FollowUpCase(
        "missing-date-hours",
        "정처기 필기 합격 계획 짜줘.",
        "시험일까지 남은 기간과 하루 공부 가능 시간을 알려주세요.",
        ("exam_date", "daily_hours"),
        ("시험일", "가용시간"),
    ),
    FollowUpCase(
        "missing-part-hours",
        "다음 주부터 정처기 공부하려고 해.",
        "필기와 실기 중 어떤 시험인지, 하루에 몇 시간 공부할 수 있는지 알려주세요.",
        ("exam_part", "daily_hours"),
        ("시험구분", "가용시간"),
    ),
    FollowUpCase(
        "missing-level-goal",
        "정보처리기사 실기 준비를 시작해야 해.",
        "현재 실기 진도와 목표 점수 또는 목표 결과를 알려주세요.",
        ("current_level", "goal"),
        ("현재수준", "목표"),
    ),
    FollowUpCase(
        "missing-hours-level",
        "정처기 실기 2주 남았는데 계획 좀.",
        "하루 공부 가능 시간과 현재 풀 수 있는 범위나 진도를 알려주세요.",
        ("daily_hours", "current_level"),
        ("가용시간", "현재수준"),
    ),
    FollowUpCase(
        "missing-weak-subject",
        "정보처리기사 필기 한 달 플랜 만들어줘.",
        "현재 가장 약한 필기 과목이나 아직 못 본 과목이 있나요?",
        ("weak_subjects",),
        ("약점",),
    ),
    FollowUpCase(
        "missing-date",
        "정처기 따고 싶은데 공부 일정 잡아줘.",
        "시험일 또는 남은 기간을 알려주세요.",
        ("exam_date",),
        ("시험일",),
    ),
    FollowUpCase(
        "missing-part",
        "정보처리기사 시험 준비 루틴 짜줘.",
        "필기와 실기 중 어떤 시험을 준비 중인가요?",
        ("exam_part",),
        ("시험구분",),
    ),
    FollowUpCase(
        "missing-hours",
        "정처기 필기 10일 남았어. 계획 세워줘.",
        "하루에 실제로 공부할 수 있는 시간은 몇 시간인가요?",
        ("daily_hours",),
        ("가용시간",),
    ),
    FollowUpCase(
        "missing-level",
        "정처기 실기 3주 계획 만들어줘.",
        "현재 개념 학습, 기출, 코드/SQL 연습 중 어디까지 진행했나요?",
        ("current_level",),
        ("현재수준",),
    ),
)


STYLE_PREFIXES = (
    "",
    "급하게 ",
    "퇴근 후에 ",
    "비전공자인데 ",
    "전공자지만 오래 쉬어서 ",
)
STYLE_SUFFIXES = (
    "",
    " 가능하면 현실적으로.",
    " 너무 빡세지 않게.",
    " 합격 기준도 반영해서.",
    " 오답 정리까지 포함해서.",
)


def _load_info(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _system(today: str) -> dict[str, str]:
    return {
        "role": "system",
        "content": runtime_system_prompt(
            today,
            extra_quality="시험 계획은 시험명·필기/실기·시험일·현재 수준·가용시간·목표를 확인",
        ),
    }


def _assistant(case: FollowUpCase) -> dict[str, Any]:
    return {
        "kind": "follow_up",
        "thread_id": "",
        "question": case.question,
        "missing_aspects": list(case.missing_aspects),
    }


def _make_user(base: str, variant: int) -> str:
    prefix = STYLE_PREFIXES[variant % len(STYLE_PREFIXES)]
    suffix = STYLE_SUFFIXES[(variant // len(STYLE_PREFIXES)) % len(STYLE_SUFFIXES)]
    return f"{prefix}{base}{suffix}".strip()


def build_samples(info: dict[str, Any], *, today: str, total: int) -> list[dict[str, Any]]:
    if total <= 0:
        return []
    official_sources = [source["url"] for source in info.get("official_sources", [])]
    rows: list[dict[str, Any]] = []
    for i in range(total):
        case = BASE_CASES[i % len(BASE_CASES)]
        variant = i // len(BASE_CASES)
        sample_id = f"ipe-followup-{case.case_id}-{variant + 1:02d}"
        rows.append(
            {
                "messages": [
                    _system(today),
                    {"role": "user", "content": _make_user(case.user, variant)},
                    {
                        "role": "assistant",
                        "content": json.dumps(_assistant(case), ensure_ascii=False),
                    },
                ],
                "meta": {
                    "id": sample_id,
                    "domain": "exam",
                    "kind": "follow_up",
                    "turn_type": "single",
                    "today": today,
                    "source": "synthetic-slot-missing",
                    "provenance": PROVENANCE,
                    "exam_code": info.get("exam_code", "information_processing_engineer"),
                    "exam_type": info.get("name", "정보처리기사"),
                    "missing_aspects": list(case.missing_aspects),
                    "tags": list(case.tags),
                    "official_sources": official_sources,
                },
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 follow_up SFT synthetic 배치 생성")
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO)
    parser.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--today", default=DEFAULT_TODAY)
    parser.add_argument("--total", type=int, default=100)
    args = parser.parse_args()

    samples = build_samples(_load_info(args.info), today=args.today, total=args.total)
    write_jsonl(samples, args.out_path)
    print(f"wrote {len(samples)} follow_up samples -> {args.out_path}")


if __name__ == "__main__":
    main()
