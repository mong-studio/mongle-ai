"""정보처리기사 runtime plan 정합성 보강 샘플 생성.

RunPod dry-run postcheck 에서 발견된 실패 유형을 직접 겨냥한다.

- due_date 는 항상 YYYY-MM-DD
- title 은 20자 이하
- tags 는 한국어만 사용
- today 와 같은 날짜는 todos, 미래 날짜는 calendar_events
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sft_pipeline.build.plan_schemas import check_plan_consistency, parse_plan
from sft_pipeline.build.prompts import runtime_system_prompt
from sft_pipeline.io_utils import write_jsonl


DEFAULT_INFO = Path("sft_pipeline/data/exam_info/information_processing_engineer.json")
DEFAULT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_hardening_sft.jsonl")
DEFAULT_TODAY = "2026-06-09"
PROVENANCE = "exam-synth"


@dataclass(frozen=True)
class PlanCase:
    case_id: str
    exam_part: str
    user: str
    weak_area: str
    horizon_days: int
    today_tasks: tuple[str, ...]
    future_tasks: tuple[tuple[int, str], ...]
    exam_event_title: str


BASE_CASES: tuple[PlanCase, ...] = (
    PlanCase(
        "written-iso-01",
        "written",
        "정보처리기사 필기 7일 남았어. 하루 2시간으로 계획 세워줘.",
        "정보시스템구축관리",
        7,
        ("합격 기준 확인", "약점 과목 정리"),
        ((1, "기출 1회 풀이"), (3, "오답 노트 정리"), (6, "최종 요약 복습")),
        "정처기 필기",
    ),
    PlanCase(
        "written-short-title",
        "written",
        "정처기 필기 14일 플랜이 필요해. 제목은 짧게 정리해줘.",
        "데이터베이스구축",
        14,
        ("오늘 범위 확정", "기출 일정 배치"),
        ((2, "DB 기출 풀이"), (7, "전과목 모의고사"), (13, "과락 점검")),
        "정처기 필기",
    ),
    PlanCase(
        "practical-korean-tags",
        "practical",
        "정보처리기사 실기 10일 남았고 SQL이 약해.",
        "SQL 응용",
        10,
        ("SQL 약점 확인", "실기 범위 점검"),
        ((1, "SQL 문제 풀이"), (5, "보안 개념 복습"), (9, "실전 답안 연습")),
        "정처기 실기",
    ),
    PlanCase(
        "practical-c5",
        "practical",
        "정처기 실기 3주 남았어. 오늘 할 일과 이후 일정을 나눠줘.",
        "프로그래밍 언어 활용",
        21,
        ("오늘 코드 복습", "답안 형식 확인"),
        ((3, "언어 문제 풀이"), (10, "통합 구현 복습"), (20, "실전 모의 풀이")),
        "정처기 실기",
    ),
    PlanCase(
        "retry-date",
        "practical",
        "실기 한 번 떨어졌고 30일 뒤 재시험이야. 날짜 틀리지 않게 계획해줘.",
        "소프트웨어 보안",
        30,
        ("불합격 원인 정리", "약점 범위 표시"),
        ((7, "보안 문제 풀이"), (15, "SQL 반복 풀이"), (29, "최종 오답 점검")),
        "정처기 실기",
    ),
)


def _load_info(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _system(today: str) -> dict[str, str]:
    return {
        "role": "system",
        "content": runtime_system_prompt(
            today,
            extra_quality="title은 20자 이하·tags는 한국어만 사용·정보처리기사 공식 과목명 반영",
        ),
    }


def _tags(case: PlanCase, extra: str) -> list[str]:
    part = "필기" if case.exam_part == "written" else "실기"
    return ["정처기", part, extra]


def _plan(case: PlanCase, *, today: date, variant: int) -> dict[str, Any]:
    todos = [
        {"title": title, "due_date": today.isoformat(), "tags": _tags(case, "오늘")}
        for title in case.today_tasks
    ]
    events = [
        {
            "title": title,
            "due_date": (today + timedelta(days=offset)).isoformat(),
            "tags": _tags(case, "미래"),
        }
        for offset, title in case.future_tasks
    ]
    events.append(
        {
            "title": case.exam_event_title,
            "due_date": (today + timedelta(days=case.horizon_days)).isoformat(),
            "tags": _tags(case, "시험"),
        }
    )
    part_name = "필기" if case.exam_part == "written" else "실기"
    return {
        "summary_text": (
            f"정보처리기사 {part_name} 준비 플랜입니다. "
            f"모든 날짜는 YYYY-MM-DD 형식이고, {case.weak_area} 보완을 우선합니다."
        ),
        "todos": todos,
        "calendar_events": events,
    }


def _user(case: PlanCase, variant: int) -> str:
    suffixes = (
        "",
        " 모든 날짜는 YYYY-MM-DD로 써줘.",
        " 제목은 20자 안으로 짧게 해줘.",
        " 태그는 한국어로만 써줘.",
        " 오늘 할 일과 미래 일정을 분리해줘.",
        " todos에는 오늘 날짜만 넣어줘.",
        " calendar_events는 내일부터만 써줘.",
        " 중국어 태그는 쓰지 말아줘.",
        " 날짜 오타 없이 작성해줘.",
        " 시험일까지 범위를 넘기지 말아줘.",
        " 각 제목을 짧은 명사구로 써줘.",
        " 정처기 공식 과목명을 반영해줘.",
        " 약점 보완 중심으로 구성해줘.",
        " 하루 할 일을 너무 많이 넣지 마.",
        " 일정 JSON만 정확히 출력해줘.",
        " C5 분기 규칙을 지켜줘.",
    )
    return f"{case.user}{suffixes[variant % len(suffixes)]}"


def _make_sample(info: dict[str, Any], case: PlanCase, *, today: date, variant: int) -> dict[str, Any]:
    plan = _plan(case, today=today, variant=variant)
    parsed = parse_plan(json.dumps(plan, ensure_ascii=False))
    errors = check_plan_consistency(parsed, today=today, horizon_days=case.horizon_days)
    if errors:
        raise ValueError(f"{case.case_id}: invalid hardening plan {errors}")
    return {
        "messages": [
            _system(today.isoformat()),
            {"role": "user", "content": _user(case, variant)},
            {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)},
        ],
        "meta": {
            "id": f"ipe-hardening-{case.case_id}-{variant + 1:02d}",
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-runtime-hardening",
            "provenance": PROVENANCE,
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": "정보처리기사 필기" if case.exam_part == "written" else "정보처리기사 실기",
            "exam_part": case.exam_part,
            "time_left_days": case.horizon_days,
            "weak_subjects": [case.weak_area],
            "hardening_targets": ["iso_date", "short_title", "korean_tags", "c5_branching"],
        },
    }


def build_samples(info: dict[str, Any], *, today: str, total: int) -> list[dict[str, Any]]:
    today_date = date.fromisoformat(today)
    rows: list[dict[str, Any]] = []
    for i in range(total):
        case = BASE_CASES[i % len(BASE_CASES)]
        variant = i // len(BASE_CASES)
        rows.append(_make_sample(info, case, today=today_date, variant=variant))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 runtime plan 정합성 보강 SFT 생성")
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO)
    parser.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--today", default=DEFAULT_TODAY)
    parser.add_argument("--total", type=int, default=80)
    args = parser.parse_args()

    samples = build_samples(_load_info(args.info), today=args.today, total=args.total)
    write_jsonl(samples, args.out_path)
    print(f"wrote {len(samples)} hardening samples -> {args.out_path}")


if __name__ == "__main__":
    main()
