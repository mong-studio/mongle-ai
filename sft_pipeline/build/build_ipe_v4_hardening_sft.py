"""postcheck v1-full 실패 유형을 겨냥한 SFT 보강 샘플 생성 (v4).

v4 타겟:
1. 연도 오타  - due_date 연도가 '2-06-08' 등으로 잘리는 문제 → 2026 명시 케이스
2. C5 복합    - '오늘+이번 주', '오늘+내일' 등 복합 기간 요청에서 C5 branch 혼동
3. route 강화 - 정보 충분한 상황에서도 follow_up 반환하는 잔존 오류
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
DEFAULT_OUT = Path("sft_pipeline/data/generated/exam_ipe_v4_hardening_sft.jsonl")
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
    """연도 4자리(2026) 출력 강화 — due_date 연도 잘림 방지."""
    case_id: str
    exam_part: str
    user: str
    today_tasks: tuple[str, ...]
    future_events: tuple[tuple[int, str], ...]
    horizon_days: int


@dataclass(frozen=True)
class C5ComplexCase:
    """복합 기간 표현("오늘+이번 주", "오늘+내일") C5 branch 케이스."""
    case_id: str
    exam_part: str
    user: str
    today_tasks: tuple[str, ...]
    future_events: tuple[tuple[int, str], ...]
    horizon_days: int


@dataclass(frozen=True)
class RouteV2Case:
    """충분한 정보가 있으므로 follow_up 없이 plan 즉시 출력 (v4 강화)."""
    case_id: str
    exam_part: str
    user: str
    weak_area: str
    horizon_days: int
    today_tasks: tuple[str, ...]
    future_tasks: tuple[tuple[int, str], ...]


# ─── 연도 오타 수정 케이스 ───────────────────

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
)


# ─── C5 복합 기간 케이스 ────────────────────

C5_COMPLEX_CASES: tuple[C5ComplexCase, ...] = (
    C5ComplexCase(
        "c5c-today-tomorrow",
        "written",
        "오늘이랑 내일 할 일 계획해줘. 정처기 필기 5일 남았어.",
        ("필기 약점 확인",),
        ((1, "내일 기출 풀기"), (4, "최종 모의고사")),
        5,
    ),
    C5ComplexCase(
        "c5c-this-week",
        "practical",
        "이번 주 정처기 실기 공부 계획 짜줘. 오늘부터 7일 남았어.",
        ("실기 범위 파악", "오늘 기출 1회"),
        ((2, "SQL 집중"), (5, "프로그래밍 실습"), (6, "최종 점검")),
        7,
    ),
    C5ComplexCase(
        "c5c-today-next-week",
        "written",
        "오늘부터 다음 주 시험까지 정처기 필기 계획 세워줘. 10일 남았어.",
        ("10일 전략 수립", "오늘 기출 분석"),
        ((3, "약점 과목 집중"), (8, "전범위 실전"), (9, "최종 오답")),
        10,
    ),
    C5ComplexCase(
        "c5c-today-3days",
        "written",
        "오늘, 내일, 모레 정처기 필기 집중 계획 알려줘. 시험은 4일 후야.",
        ("오늘 핵심 확인",),
        ((1, "내일 약점 집중"), (2, "모레 모의고사"), (3, "전날 최종 정리")),
        4,
    ),
    C5ComplexCase(
        "c5c-week-plan",
        "practical",
        "정처기 실기 1주일 계획 잡아줘. 오늘 시작해서 7일 뒤 시험이야.",
        ("실기 약점 표시", "오늘 기출 확인"),
        ((2, "SQL 기출"), (5, "프로그래밍 집중"), (6, "최종 실전")),
        7,
    ),
    C5ComplexCase(
        "c5c-today-rest",
        "written",
        "오늘 할 것 먼저 알려주고, 나머지 14일 일정도 잡아줘.",
        ("오늘 우선순위 결정", "14일 전략 수립"),
        ((3, "약점 과목"), (8, "전범위 기출"), (13, "최종 오답")),
        14,
    ),
    C5ComplexCase(
        "c5c-today-split-explicit",
        "practical",
        "오늘 할 일(todos)과 앞으로 일정(calendar_events)을 나눠서 정처기 실기 D-21 계획 만들어줘.",
        ("실기 전략 수립", "약점 파악"),
        ((5, "약점 집중"), (14, "실전 풀이"), (20, "최종 점검")),
        21,
    ),
)


# ─── route v2 강화 케이스 ───────────────────

ROUTE_V2_CASES: tuple[RouteV2Case, ...] = (
    RouteV2Case(
        "rv2-written-5d",
        "written",
        "정처기 필기 5일 남았고 5과목이 약해. 하루 4시간 공부 가능. 지금 바로 계획 줘.",
        "프로그래밍언어활용",
        5,
        ("5과목 핵심 정리", "기출 약점 표시"),
        ((2, "5과목 집중 풀이"), (4, "전범위 실전")),
    ),
    RouteV2Case(
        "rv2-practical-7d",
        "practical",
        "정처기 실기 7일 남았어. SQL 약하고 하루 5시간. 바로 plan으로 만들어줘.",
        "SQL 응용",
        7,
        ("SQL 약점 파악", "기출 답안 형식 확인"),
        ((3, "SQL 기출 집중"), (6, "최종 실전 점검")),
    ),
    RouteV2Case(
        "rv2-written-14d",
        "written",
        "정처기 필기 2주 남았고 DB 과목이 약해. 하루 2시간 가능. follow_up 없이 plan 바로 줘.",
        "데이터베이스구축",
        14,
        ("DB 핵심 개념 확인", "기출 약점 표시"),
        ((5, "DB 기출 집중"), (12, "전범위 모의고사"), (13, "최종 오답")),
    ),
    RouteV2Case(
        "rv2-practical-30d",
        "practical",
        "정처기 실기 한 달 남았어. 소프트웨어 설계 약하고 하루 3시간. 질문 없이 계획 만들어줘.",
        "소프트웨어 설계",
        30,
        ("설계 약점 확인", "기출 범위 파악"),
        ((7, "설계 기출 집중"), (20, "전범위 실전"), (29, "최종 오답 점검")),
    ),
    RouteV2Case(
        "rv2-written-3d",
        "written",
        "필기 3일 남았고 하루 6시간 공부 가능. 1·2과목 약해. 지금 당장 JSON으로 계획 줘.",
        "소프트웨어설계, 소프트웨어개발",
        3,
        ("1과목 핵심 정리", "2과목 기출 확인"),
        ((1, "1·2과목 집중"), (2, "전범위 최종 모의")),
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

C5_COMPLEX_SUFFIXES = (
    "",
    " todos에는 오늘 날짜만, 나머지는 calendar_events.",
    " 오늘 할 일만 todos, 내일 이후는 calendar_events.",
    " due_date가 오늘인 항목만 todos에 넣어줘.",
    " 오늘 날짜가 아닌 건 todos에 절대 넣지 마.",
    " todos = 오늘만, calendar_events = 이후 일정.",
    " 코드블록 없이 순수 JSON으로.",
    " due_date는 YYYY-MM-DD 형식으로 정확히.",
    " 태그는 한국어만 사용해줘.",
)

ROUTE_V2_SUFFIXES = (
    "",
    " 필요한 정보 다 있으니 follow_up 없이 plan으로 바로 줘.",
    " 추가 질문 없이 plan JSON만 만들어줘.",
    " follow_up 대신 summary_text·todos·calendar_events로.",
    " 정보가 충분하므로 plan을 즉시 출력해줘.",
    " JSON 앞뒤 설명 없이 plan만.",
    " 코드블록 없이 순수 JSON.",
    " 시험일은 calendar_events, 오늘 할 일은 todos.",
    " due_date는 2026-MM-DD 형식으로.",
    " 태그는 한국어만, title 20자 이내.",
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
    summary = (
        f"정처기 {_part_label(case.exam_part)} D-{case.horizon_days} 플랜입니다. "
        f"모든 due_date는 {today.year} 연도 YYYY-MM-DD 형식으로 작성합니다."
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
            "id": f"ipe-v4-year-{case.case_id}-{variant + 1:03d}",
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-v4-hardening",
            "provenance": PROVENANCE,
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": f"정보처리기사 {_part_label(case.exam_part)}",
            "exam_part": case.exam_part,
            "time_left_days": case.horizon_days,
            "hardening_targets": ["year_4digit", "due_date_2026", "c5_branch"],
        },
    }


def _c5c_sample(info: dict, case: C5ComplexCase, *, today: date, variant: int) -> dict[str, Any]:
    summary = (
        f"정처기 {_part_label(case.exam_part)} D-{case.horizon_days} 플랜입니다. "
        "복합 기간 요청이지만 todos는 오늘 날짜만, 이후 일정은 calendar_events에 분리합니다."
    )
    plan = _build_plan(
        case.exam_part, case.today_tasks, case.future_events,
        case.horizon_days, today, summary,
    )
    parsed = parse_plan(json.dumps(plan, ensure_ascii=False))
    errors = check_plan_consistency(parsed, today=today, horizon_days=case.horizon_days)
    if errors:
        raise ValueError(f"c5c {case.case_id}: {errors}")
    all_suffixes = C5_COMPLEX_SUFFIXES + _date_suffixes(today)
    suffix = all_suffixes[variant % len(all_suffixes)]
    return {
        "messages": [
            _system(today.isoformat()),
            {"role": "user", "content": f"{case.user}{suffix}"},
            {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)},
        ],
        "meta": {
            "id": f"ipe-v4-c5c-{case.case_id}-{variant + 1:03d}",
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-v4-hardening",
            "provenance": PROVENANCE,
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": f"정보처리기사 {_part_label(case.exam_part)}",
            "exam_part": case.exam_part,
            "time_left_days": case.horizon_days,
            "hardening_targets": ["c5_branch", "todos_today_only", "complex_period"],
        },
    }


def _rv2_sample(info: dict, case: RouteV2Case, *, today: date, variant: int) -> dict[str, Any]:
    summary = (
        f"정처기 {_part_label(case.exam_part)} 준비 플랜입니다. "
        f"충분한 정보(시험일·약점·가용시간)가 있으므로 {case.weak_area} 보완 중심으로 즉시 계획합니다."
    )
    plan = _build_plan(
        case.exam_part, case.today_tasks, case.future_tasks,
        case.horizon_days, today, summary,
    )
    parsed = parse_plan(json.dumps(plan, ensure_ascii=False))
    errors = check_plan_consistency(parsed, today=today, horizon_days=case.horizon_days)
    if errors:
        raise ValueError(f"rv2 {case.case_id}: {errors}")
    all_suffixes = ROUTE_V2_SUFFIXES + _date_suffixes(today)
    suffix = all_suffixes[variant % len(all_suffixes)]
    return {
        "messages": [
            _system(today.isoformat()),
            {"role": "user", "content": f"{case.user}{suffix}"},
            {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)},
        ],
        "meta": {
            "id": f"ipe-v4-rv2-{case.case_id}-{variant + 1:03d}",
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-v4-hardening",
            "provenance": PROVENANCE,
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": f"정보처리기사 {_part_label(case.exam_part)}",
            "exam_part": case.exam_part,
            "time_left_days": case.horizon_days,
            "weak_subjects": [case.weak_area],
            "hardening_targets": ["route_plan_v2", "no_followup_when_sufficient"],
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
    c5c_total: int,
    rv2_total: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for i in range(year_total):
        today_i = date.fromisoformat(DATE_POOL[i % len(DATE_POOL)])
        rows.append(_year_sample(info, YEAR_CASES[i % len(YEAR_CASES)], today=today_i, variant=i))

    for i in range(c5c_total):
        today_i = date.fromisoformat(DATE_POOL[i % len(DATE_POOL)])
        rows.append(_c5c_sample(info, C5_COMPLEX_CASES[i % len(C5_COMPLEX_CASES)], today=today_i, variant=i))

    for i in range(rv2_total):
        today_i = date.fromisoformat(DATE_POOL[i % len(DATE_POOL)])
        rows.append(_rv2_sample(info, ROUTE_V2_CASES[i % len(ROUTE_V2_CASES)], today=today_i, variant=i))

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="postcheck v1-full 실패 유형 보강 SFT 생성 (v4)")
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO)
    parser.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--today", default=DEFAULT_TODAY)
    parser.add_argument("--year-total", type=int, default=30)
    parser.add_argument("--c5c-total", type=int, default=50)
    parser.add_argument("--rv2-total", type=int, default=20)
    args = parser.parse_args()

    samples = build_samples(
        _load_info(args.info),
        today=args.today,
        year_total=args.year_total,
        c5c_total=args.c5c_total,
        rv2_total=args.rv2_total,
    )
    write_jsonl(samples, args.out_path)
    print(f"wrote {len(samples)} v4 hardening samples -> {args.out_path}")
    year_n = sum(1 for s in samples if "year_4digit" in s["meta"].get("hardening_targets", []))
    c5c_n = sum(1 for s in samples if "complex_period" in s["meta"].get("hardening_targets", []))
    rv2_n = sum(1 for s in samples if "route_plan_v2" in s["meta"].get("hardening_targets", []))
    print(f"  year_4digit: {year_n}, c5c_complex: {c5c_n}, route_v2: {rv2_n}")


if __name__ == "__main__":
    main()
