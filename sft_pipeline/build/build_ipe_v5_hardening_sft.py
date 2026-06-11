"""postcheck v2b 실패 유형을 겨냥한 SFT 보강 샘플 생성 (v5).

v5 타겟:
1. 연도 오타 (year_fix)  - '2206-06-XX' 자릿수 뒤바뀜 패턴 → 다양한 기준일로 2026- 반복 노출
2. C5 branch 강화 (c5)   - todos = 기준일 당일만, 미래 일정은 calendar_events 규칙 강화

v4 대비 변경:
- 연도: summary_text에 오늘 날짜 전체를 명시해 year 학습 신호 강화
- C5: 케이스 10종으로 확장, 80건 생성, suffix에 오늘 날짜 명시 비율 높임
- 두 타겟을 완전히 분리하여 상호 간섭 방지
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
DEFAULT_OUT = Path("sft_pipeline/data/generated/exam_ipe_v5_hardening_sft.jsonl")
DEFAULT_TODAY = "2026-06-10"
PROVENANCE = "exam-synth"

DATE_POOL = (
    "2026-06-01", "2026-06-03", "2026-06-05", "2026-06-08",
    "2026-06-10", "2026-06-12", "2026-06-15", "2026-06-18",
    "2026-06-20", "2026-06-25",
)


# ─────────────────────────────────────────────
# 케이스 정의
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class YearFixCase:
    """연도 2026 출력 강화 — '2206-' 자릿수 뒤바뀜 방지."""
    case_id: str
    exam_part: str
    user: str
    today_tasks: tuple[str, ...]
    future_events: tuple[tuple[int, str], ...]
    horizon_days: int


@dataclass(frozen=True)
class C5Case:
    """C5 branch 강화 — todos = 기준일 당일만, 미래 = calendar_events."""
    case_id: str
    exam_part: str
    user: str
    today_tasks: tuple[str, ...]
    future_events: tuple[tuple[int, str], ...]
    horizon_days: int


# ─── 연도 오타 수정 케이스 (10종) ──────────────

YEAR_CASES: tuple[YearFixCase, ...] = (
    YearFixCase(
        "year-written-7d",
        "written",
        "정처기 필기 시험 7일 남았어. 오늘부터 시작할게.",
        ("기출 분석", "핵심 개념 정리"),
        ((3, "약점 과목 풀이"), (6, "최종 모의고사")),
        7,
    ),
    YearFixCase(
        "year-practical-14d",
        "practical",
        "정처기 실기 14일 남았어. 오늘 할 일이랑 앞으로 일정 짜줘.",
        ("실기 약점 확인", "SQL 기출 풀기"),
        ((5, "프로그래밍 집중"), (12, "전범위 실전"), (13, "최종 오답")),
        14,
    ),
    YearFixCase(
        "year-written-30d",
        "written",
        "정처기 필기 한 달 남았어. 공부 계획 잡아줘.",
        ("DB 핵심 확인", "1과목 기출"),
        ((7, "2과목 집중"), (20, "모의고사"), (29, "오답 복습")),
        30,
    ),
    YearFixCase(
        "year-practical-21d",
        "practical",
        "정처기 실기 21일 남았어. 하루 3시간 가능해. 계획 짜줘.",
        ("보안 약점 정리", "SQL 오답 확인"),
        ((5, "보안 기출"), (14, "SQL 실전"), (20, "최종 점검")),
        21,
    ),
    YearFixCase(
        "year-written-10d",
        "written",
        "정처기 필기 D-10이야. 오늘부터 계획 세워줘.",
        ("핵심 범위 확정", "빈출 개념 정리"),
        ((3, "약점 과목 집중"), (8, "전범위 실전"), (9, "오답 총정리")),
        10,
    ),
    YearFixCase(
        "year-practical-5d",
        "practical",
        "정처기 실기 5일 남았어. 마무리 계획 줘.",
        ("실기 약점 최종 확인",),
        ((2, "SQL 집중 풀이"), (4, "전범위 실전")),
        5,
    ),
    YearFixCase(
        "year-written-3d",
        "written",
        "정처기 필기 3일 남았어. 마지막 점검 계획 세워줘.",
        ("오늘 기출 집중",),
        ((1, "약점 최종 정리"), (2, "D-1 최종 점검")),
        3,
    ),
    YearFixCase(
        "year-practical-60d",
        "practical",
        "정처기 실기 2달 남았어. 장기 계획 잡아줘.",
        ("현재 수준 파악", "학습 전략 수립"),
        ((14, "1차 기출 풀이"), (40, "중간 점검"), (59, "최종 실전")),
        60,
    ),
    YearFixCase(
        "year-written-45d",
        "written",
        "정처기 필기 45일 남았어. 장기 계획 세워줘.",
        ("전 과목 파악", "약점 과목 선정"),
        ((10, "1·2과목 집중"), (25, "3·4과목 집중"), (44, "전범위 실전")),
        45,
    ),
    YearFixCase(
        "year-practical-4d",
        "practical",
        "정처기 실기 D-4야. 빠르게 계획 줘.",
        ("오늘 핵심 확인", "기출 일정 배치"),
        ((2, "약점 과목 풀이"), (3, "최종 오답")),
        4,
    ),
)


# ─── C5 branch 강화 케이스 (10종) ────────────

C5_CASES: tuple[C5Case, ...] = (
    C5Case(
        "c5-today-only",
        "written",
        "오늘 할 일만 알려줘. 정처기 필기 5일 남았어.",
        ("필기 약점 확인", "오늘 기출 풀기"),
        ((2, "약점 집중"), (4, "최종 모의고사")),
        5,
    ),
    C5Case(
        "c5-today-tomorrow",
        "written",
        "오늘이랑 내일 할 일 계획해줘. 정처기 필기 5일 남았어.",
        ("필기 약점 확인",),
        ((1, "내일 기출 풀기"), (4, "최종 모의고사")),
        5,
    ),
    C5Case(
        "c5-this-week",
        "practical",
        "이번 주 정처기 실기 공부 계획 짜줘. 오늘부터 7일 남았어.",
        ("실기 범위 파악", "오늘 기출 1회"),
        ((2, "SQL 집중"), (5, "프로그래밍 실습"), (6, "최종 점검")),
        7,
    ),
    C5Case(
        "c5-today-next-week",
        "written",
        "오늘부터 다음 주 시험까지 정처기 필기 계획 세워줘. 10일 남았어.",
        ("10일 전략 수립", "오늘 기출 분석"),
        ((3, "약점 과목 집중"), (8, "전범위 실전"), (9, "최종 오답")),
        10,
    ),
    C5Case(
        "c5-today-3days",
        "written",
        "오늘, 내일, 모레 정처기 필기 집중 계획 알려줘. 시험은 4일 후야.",
        ("오늘 핵심 확인",),
        ((1, "내일 약점 집중"), (2, "모레 모의고사"), (3, "전날 최종 정리")),
        4,
    ),
    C5Case(
        "c5-week-plan",
        "practical",
        "정처기 실기 1주일 계획 잡아줘. 오늘 시작해서 7일 뒤 시험이야.",
        ("실기 약점 표시", "오늘 기출 확인"),
        ((2, "SQL 기출"), (5, "프로그래밍 집중"), (6, "최종 실전")),
        7,
    ),
    C5Case(
        "c5-today-rest",
        "written",
        "오늘 할 것 먼저 알려주고, 나머지 14일 일정도 잡아줘.",
        ("오늘 우선순위 결정", "14일 전략 수립"),
        ((3, "약점 과목"), (8, "전범위 기출"), (13, "최종 오답")),
        14,
    ),
    C5Case(
        "c5-split-explicit",
        "practical",
        "오늘 할 일(todos)과 앞으로 일정(calendar_events)을 나눠서 정처기 실기 D-21 계획 만들어줘.",
        ("실기 전략 수립", "약점 파악"),
        ((5, "약점 집중"), (14, "실전 풀이"), (20, "최종 점검")),
        21,
    ),
    C5Case(
        "c5-written-d14-complex",
        "written",
        "정처기 필기 2주 남았어. 오늘 할 것과 앞으로 일정 나눠줘.",
        ("DB 핵심 확인", "오늘 기출 1회"),
        ((4, "약점 과목 집중"), (10, "모의고사"), (13, "최종 오답")),
        14,
    ),
    C5Case(
        "c5-practical-d30-daily",
        "practical",
        "정처기 실기 한 달 남았어. 오늘부터 시작해서 매일 계획 잡아줘.",
        ("실기 전략 수립", "오늘 범위 파악"),
        ((7, "SQL 집중"), (20, "프로그래밍 실습"), (29, "최종 실전")),
        30,
    ),
)


# ─────────────────────────────────────────────
# suffix 변형
# ─────────────────────────────────────────────

YEAR_SUFFIXES = (
    "",
    " due_date는 YYYY-MM-DD 형식으로 정확히 써줘.",
    " 코드블록 없이 순수 JSON으로 답해줘.",
    " 태그는 한국어만, title은 20자 이내로.",
    " todos는 오늘만, 나머지는 calendar_events에.",
    " JSON 하나만 출력해줘.",
    " 날짜 형식 YYYY-MM-DD로 정확히.",
    " 태그는 한국어만 사용해줘.",
    " 코드블록 없이 순수 JSON.",
    " todos는 오늘 날짜만 사용해줘.",
)

C5_SUFFIXES = (
    "",
    " todos에는 오늘 날짜만, 나머지는 calendar_events.",
    " 오늘 할 일만 todos, 내일 이후는 calendar_events.",
    " due_date가 오늘인 항목만 todos에 넣어줘.",
    " 오늘 날짜가 아닌 건 todos에 절대 넣지 마.",
    " todos = 오늘만, calendar_events = 이후 일정.",
    " 코드블록 없이 순수 JSON으로.",
    " due_date는 YYYY-MM-DD 형식으로 정확히.",
    " 태그는 한국어만 사용해줘.",
    " 오늘 날짜만 todos, 미래는 calendar_events.",
    " todos의 due_date는 전부 오늘이어야 해.",
)


def _date_suffixes(today: date) -> tuple[str, ...]:
    d = today.isoformat()
    return (
        f" 오늘 날짜가 {d}이니까 todos에는 {d}만 써줘.",
        f" todos의 due_date는 전부 {d}여야 해.",
        f" 기준일({d})에 할 일은 todos에, 그 이후는 calendar_events에.",
        f" {d} 기준으로 오늘 할 일과 미래 일정을 분리해줘.",
        f" due_date는 YYYY-MM-DD 형식으로 정확히.",
    )


# ─────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────

def _load_info(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _system(today: str) -> dict[str, str]:
    return {
        "role": "system",
        "content": runtime_system_prompt(
            today,
            extra_quality=(
                "todos는 기준일 당일만·미래 일정은 calendar_events·"
                "충분한 정보면 follow_up 금지·due_date는 YYYY-MM-DD 형식"
            ),
        ),
    }


def _part_label(exam_part: str) -> str:
    return "필기" if exam_part == "written" else "실기"


def _base_tags(exam_part: str) -> list[str]:
    return ["정처기", _part_label(exam_part)]


def _build_plan(
    exam_part: str,
    today_tasks: tuple[str, ...],
    future_events: tuple[tuple[int, str], ...],
    horizon_days: int,
    today: date,
    summary: str,
) -> dict[str, Any]:
    todos = [
        {"title": t, "due_date": today.isoformat(), "tags": _base_tags(exam_part) + ["오늘"]}
        for t in today_tasks
    ]
    calendar_events = [
        {
            "title": title,
            "due_date": (today + timedelta(days=offset)).isoformat(),
            "tags": _base_tags(exam_part) + ["미래"],
        }
        for offset, title in future_events
    ]
    calendar_events.append({
        "title": f"정처기 {_part_label(exam_part)} 시험",
        "due_date": (today + timedelta(days=horizon_days)).isoformat(),
        "tags": _base_tags(exam_part) + ["시험"],
    })
    return {"summary_text": summary, "todos": todos, "calendar_events": calendar_events}


# ─────────────────────────────────────────────
# 샘플 생성
# ─────────────────────────────────────────────

def _year_sample(info: dict, case: YearFixCase, *, today: date, variant: int) -> dict[str, Any]:
    # summary에 오늘 날짜 전체를 명시 — year 학습 신호를 assistant 출력에서 강화
    summary = (
        f"정처기 {_part_label(case.exam_part)} D-{case.horizon_days} 플랜입니다. "
        f"오늘은 {today.isoformat()}이므로 todos due_date는 {today.isoformat()}, "
        f"calendar_events는 {today.isoformat()[:4]}-MM-DD 형식으로 작성합니다."
    )
    plan = _build_plan(
        case.exam_part, case.today_tasks, case.future_events,
        case.horizon_days, today, summary,
    )
    parsed = parse_plan(json.dumps(plan, ensure_ascii=False))
    errors = check_plan_consistency(parsed, today=today, horizon_days=case.horizon_days)
    if errors:
        raise ValueError(f"year {case.case_id}: {errors}")
    all_suffixes = YEAR_SUFFIXES + _date_suffixes(today)
    suffix = all_suffixes[variant % len(all_suffixes)]
    return {
        "messages": [
            _system(today.isoformat()),
            {"role": "user", "content": f"{case.user}{suffix}"},
            {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)},
        ],
        "meta": {
            "id": f"ipe-v5-year-{case.case_id}-{variant + 1:03d}",
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-v5-hardening",
            "provenance": PROVENANCE,
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": f"정보처리기사 {_part_label(case.exam_part)}",
            "exam_part": case.exam_part,
            "time_left_days": case.horizon_days,
            "hardening_targets": ["year_fix_v5", "due_date_format"],
        },
    }


def _c5_sample(info: dict, case: C5Case, *, today: date, variant: int) -> dict[str, Any]:
    summary = (
        f"정처기 {_part_label(case.exam_part)} D-{case.horizon_days} 플랜입니다. "
        f"todos는 오늘({today.isoformat()}) 날짜만 사용하고, "
        "이후 일정은 모두 calendar_events에 분리합니다."
    )
    plan = _build_plan(
        case.exam_part, case.today_tasks, case.future_events,
        case.horizon_days, today, summary,
    )
    parsed = parse_plan(json.dumps(plan, ensure_ascii=False))
    errors = check_plan_consistency(parsed, today=today, horizon_days=case.horizon_days)
    if errors:
        raise ValueError(f"c5 {case.case_id}: {errors}")
    all_suffixes = C5_SUFFIXES + _date_suffixes(today)
    suffix = all_suffixes[variant % len(all_suffixes)]
    return {
        "messages": [
            _system(today.isoformat()),
            {"role": "user", "content": f"{case.user}{suffix}"},
            {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)},
        ],
        "meta": {
            "id": f"ipe-v5-c5-{case.case_id}-{variant + 1:03d}",
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-v5-hardening",
            "provenance": PROVENANCE,
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": f"정보처리기사 {_part_label(case.exam_part)}",
            "exam_part": case.exam_part,
            "time_left_days": case.horizon_days,
            "hardening_targets": ["c5_branch_v5", "todos_today_only"],
        },
    }


# ─────────────────────────────────────────────
# 메인 빌드
# ─────────────────────────────────────────────

def build_samples(
    info: dict[str, Any],
    *,
    today: str,
    year_total: int,
    c5_total: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for i in range(year_total):
        today_i = date.fromisoformat(DATE_POOL[i % len(DATE_POOL)])
        rows.append(_year_sample(info, YEAR_CASES[i % len(YEAR_CASES)], today=today_i, variant=i))

    for i in range(c5_total):
        today_i = date.fromisoformat(DATE_POOL[i % len(DATE_POOL)])
        rows.append(_c5_sample(info, C5_CASES[i % len(C5_CASES)], today=today_i, variant=i))

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="postcheck v2b 실패 유형 보강 SFT 생성 (v5)")
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO)
    parser.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--today", default=DEFAULT_TODAY)
    parser.add_argument("--year-total", type=int, default=50)
    parser.add_argument("--c5-total", type=int, default=80)
    args = parser.parse_args()

    samples = build_samples(
        _load_info(args.info),
        today=args.today,
        year_total=args.year_total,
        c5_total=args.c5_total,
    )
    write_jsonl(samples, args.out_path)
    print(f"wrote {len(samples)} v5 hardening samples -> {args.out_path}")
    year_n = sum(1 for s in samples if "year_fix_v5" in s["meta"].get("hardening_targets", []))
    c5_n = sum(1 for s in samples if "c5_branch_v5" in s["meta"].get("hardening_targets", []))
    print(f"  year_fix: {year_n}, c5_branch: {c5_n}")


if __name__ == "__main__":
    main()
