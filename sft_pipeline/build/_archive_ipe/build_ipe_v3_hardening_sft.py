"""postcheck v3 실패 유형을 겨냥한 SFT 보강 샘플 생성.

v3 타겟:
1. C5 branch  - todos는 기준일 당일만, 미래는 calendar_events
2. follow_up  - question 필드 반드시 포함
3. plan route - 충분한 정보 있으면 follow_up 없이 plan 즉시 출력
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sft_pipeline.build.lib.plan_schemas import check_plan_consistency, parse_plan
from sft_pipeline.build.lib.prompts import runtime_system_prompt
from sft_pipeline.io_utils import write_jsonl


DEFAULT_INFO = Path("sft_pipeline/data/exam_info/information_processing_engineer.json")
DEFAULT_OUT = Path("sft_pipeline/data/generated/exam_ipe_v3_hardening_sft.jsonl")
DEFAULT_TODAY = "2026-06-10"
PROVENANCE = "exam-synth"

# 날짜 앵커링 방지: 샘플마다 기준일을 순환
DATE_POOL = (
    "2026-06-01", "2026-06-03", "2026-06-05", "2026-06-08",
    "2026-06-10", "2026-06-12", "2026-06-15", "2026-06-18",
    "2026-06-20", "2026-06-25",
)


# ─────────────────────────────────────────────
# 케이스 정의
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class C5PlanCase:
    """C5 branch 타겟: todos = 오늘, calendar_events = 미래."""
    case_id: str
    exam_part: str
    user: str
    today_tasks: tuple[str, ...]
    future_events: tuple[tuple[int, str], ...]
    horizon_days: int


@dataclass(frozen=True)
class PlanRouteCase:
    """충분한 정보가 있으므로 follow_up 없이 plan 바로 출력."""
    case_id: str
    exam_part: str
    user: str
    weak_area: str
    horizon_days: int
    today_tasks: tuple[str, ...]
    future_tasks: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class FollowUpCase:
    """question 필드를 반드시 포함하는 follow_up 케이스."""
    case_id: str
    user: str
    question: str
    missing_aspects: tuple[str, ...]


# ─── C5 branch 집중 케이스 ───────────────────

C5_CASES: tuple[C5PlanCase, ...] = (
    C5PlanCase(
        "c5-sql-7d",
        "practical",
        "오늘 SQL 문제 풀고 7일 뒤 시험이야. 오늘 할 일과 일정을 나눠서 계획 짜줘.",
        ("SQL 약점 확인", "오늘 기출 1회 풀기"),
        ((3, "SQL 심화 연습"), (6, "최종 실전 풀이")),
        7,
    ),
    C5PlanCase(
        "c5-written-14d",
        "written",
        "정처기 필기 14일 남았어. 오늘 바로 시작할 할 일이랑 앞으로 일정을 구분해서 알려줘.",
        ("필기 약점 과목 확인", "1과목 기출 훑기"),
        ((4, "2·3과목 기출 풀이"), (10, "전과목 모의고사"), (13, "오답 최종 정리")),
        14,
    ),
    C5PlanCase(
        "c5-retry-practical",
        "practical",
        "실기 재시험 30일 남았어. 오늘 시작할 것과 시험까지 일정을 따로 보여줘.",
        ("불합격 원인 정리", "약점 과목 우선순위"),
        ((7, "약점 집중 풀이"), (20, "전범위 실전 풀이"), (29, "최종 오답 체크")),
        30,
    ),
    C5PlanCase(
        "c5-short-3d",
        "written",
        "정처기 필기 3일 밖에 안 남았어. 오늘 반드시 할 것이랑 이후 일정 알려줘.",
        ("출제 빈도 높은 파트 확인", "기출 핵심 문제 풀기"),
        ((1, "2·3과목 요점 복습"), (2, "최종 실전 모의고사")),
        3,
    ),
    C5PlanCase(
        "c5-today-only",
        "practical",
        "오늘 정처기 실기 공부 시작하는데, todos에 오늘 날짜만 넣고 시험 일정은 calendar_events에 넣어줘.",
        ("실기 범위 파악", "답안 형식 확인"),
        ((10, "SQL 기출 풀이"), (25, "프로그래밍 실습 마무리")),
        30,
    ),
)

# ─── plan routing 케이스 ─────────────────────

PLAN_ROUTE_CASES: tuple[PlanRouteCase, ...] = (
    PlanRouteCase(
        "route-written-7d",
        "written",
        "정처기 필기 7일 남았고 하루 3시간 가능해. 4·5과목 약해. 목표 합격.",
        "프로그래밍언어활용, 정보시스템구축관리",
        7,
        ("약점 범위 확정", "과락 기준 확인"),
        ((2, "4과목 기출"), (5, "5과목 오답"), (6, "최종 모의")),
    ),
    PlanRouteCase(
        "route-practical-10d",
        "practical",
        "정처기 실기 10일 남았고 SQL·프로그래밍 약해. 하루 4시간 가능.",
        "SQL 응용, 프로그래밍 언어 활용",
        10,
        ("SQL 약점 확인", "답안 형식 점검"),
        ((3, "SQL 기출"), (7, "코드 추적 연습"), (9, "실전 답안 복습")),
    ),
    PlanRouteCase(
        "route-written-30d",
        "written",
        "다음 달 정처기 필기 시험이야. 하루 2시간 가능하고 데이터베이스가 제일 약해.",
        "데이터베이스구축",
        30,
        ("DB 핵심 개념 파악", "기출 약점 표시"),
        ((7, "DB 기출 풀이"), (20, "전과목 모의고사"), (29, "오답 최종 복습")),
    ),
    PlanRouteCase(
        "route-practical-21d",
        "practical",
        "정처기 실기 21일 남았어. 소프트웨어 보안이랑 SQL이 약하고 하루 3시간.",
        "소프트웨어 보안, SQL 응용",
        21,
        ("보안 약점 정리", "SQL 오답 확인"),
        ((5, "보안 기출 집중"), (14, "SQL 실전 풀이"), (20, "최종 오답 점검")),
    ),
    PlanRouteCase(
        "route-written-21d",
        "written",
        "정처기 필기 3주 남았어. 1·2과목이 약하고 하루 1.5시간. 계획만 JSON으로 줘.",
        "소프트웨어설계, 소프트웨어개발",
        21,
        ("1과목 요점 정리", "2과목 기출 확인"),
        ((7, "1·2과목 집중 풀이"), (14, "전과목 모의고사"), (20, "최종 오답 복습")),
    ),
)

# ─── follow_up schema 케이스 ─────────────────

FOLLOWUP_CASES: tuple[FollowUpCase, ...] = (
    FollowUpCase(
        "fu-type-date",
        "정보처리기사 공부 시작하려고.",
        "필기와 실기 중 어떤 시험을 준비하시나요?",
        ("시험 유형",),
    ),
    FollowUpCase(
        "fu-date-only",
        "정처기 계획 잡아줘.",
        "시험일 또는 남은 기간이 어떻게 되나요?",
        ("시험일 또는 남은 기간",),
    ),
    FollowUpCase(
        "fu-hours-level",
        "정처기 실기 3주 계획 만들어줘.",
        "현재 실기 진도와 하루 공부 가능 시간을 알려주세요.",
        ("현재 진도", "하루 가용 시간"),
    ),
    FollowUpCase(
        "fu-weak-subject",
        "정처기 필기 한 달 남았어. 계획 세워줘.",
        "현재 가장 약한 과목과 하루 공부 가능 시간을 알려주세요.",
        ("약점 과목", "하루 가용 시간"),
    ),
    FollowUpCase(
        "fu-goal",
        "정보처리기사 필기 공부 루틴 짜줘.",
        "시험일까지 남은 기간과 목표 결과를 알려주세요.",
        ("시험일까지 남은 기간", "목표"),
    ),
    FollowUpCase(
        "fu-practical-missing",
        "정처기 실기 준비하려고 하는데 도와줘.",
        "시험일 또는 남은 기간과 하루 공부 가능 시간을 알려주세요.",
        ("시험일 또는 남은 기간", "하루 가용 시간"),
    ),
)


# ─────────────────────────────────────────────
# suffix 변형 (중복 방지)
# ─────────────────────────────────────────────

C5_SUFFIXES = (
    "",
    " todos에는 오늘 날짜만 넣어줘.",
    " 오늘 할 일과 미래 일정을 반드시 분리해줘.",
    " todos는 기준일 당일 날짜만 사용해줘.",
    " 미래 일정은 전부 calendar_events에 넣어줘.",
    " 오늘 날짜가 아닌 할 일은 todos에 넣지 마.",
    " JSON 하나만 출력해줘.",
    " due_date는 YYYY-MM-DD 형식으로 정확히 써줘.",
    " 코드블록 없이 순수 JSON으로 답해줘.",
    " 태그는 한국어로만 써줘. 영문 태그 금지.",
    " title은 20자 안으로 써줘.",
    " 오늘 할 일: todos, 미래 일정: calendar_events로만 구분해줘.",
    " tags는 '정처기', '필기', '실기' 같은 한국어만 사용해줘.",
    " 영문 태그(exam, study 등)는 사용하지 마.",
)

PLAN_ROUTE_SUFFIXES = (
    "",
    " 충분한 정보가 있으니 follow_up 없이 plan만 출력해줘.",
    " 질문하지 말고 바로 계획 JSON을 만들어줘.",
    " 추가 질문 없이 plan 하나만 줘.",
    " follow_up 대신 summary_text·todos·calendar_events로 출력해줘.",
    " 이미 필요한 정보 다 줬으니 바로 실행 계획을 만들어줘.",
    " JSON 앞뒤 설명 없이 plan만 줘.",
    " 코드블록 없이 순수 JSON으로만 답해줘.",
    " 태그는 한국어만, title은 20자 이내로 써줘.",
    " 시험일은 calendar_events에, 오늘 할 일은 todos에만 넣어줘.",
    " due_date는 YYYY-MM-DD 형식으로 정확히 써줘.",
    " 정보가 충분하니 follow_up 질문 하지 마.",
)

FOLLOWUP_SUFFIXES = (
    "",
    " question 필드에 질문을 넣어줘.",
    " missing_aspects 배열과 question 필드를 반드시 포함해줘.",
    " JSON 하나만 출력해줘.",
    " question과 missing_aspects만으로 부족 정보를 물어봐줘.",
    " kind는 follow_up이고 question 필드가 반드시 있어야 해.",
    " 코드블록 없이 순수 JSON으로 답해줘.",
    " 부족한 정보 하나만 짧게 물어봐줘.",
    " follow_up JSON에 question 키를 꼭 넣어줘.",
    " 추가 설명 대신 question 한 줄만 만들어줘.",
)


# ─────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────

def _date_suffixes(today: date) -> tuple[str, ...]:
    """today를 포함한 동적 suffix — C5 날짜 앵커링 방지."""
    d = today.isoformat()
    return (
        f" 오늘 날짜가 {d}이니까 todos에는 {d}만 써줘.",
        f" todos의 due_date는 전부 {d}여야 해.",
        f" 기준일({d})에 할 일은 todos에, 그 이후는 calendar_events에.",
        f" {d} 기준으로 오늘 할 일과 미래 일정을 분리해줘.",
    )


def _load_info(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _system(today: str) -> dict[str, str]:
    return {
        "role": "system",
        "content": runtime_system_prompt(
            today,
            extra_quality=(
                "todos는 기준일 당일만·미래 일정은 calendar_events·"
                "충분한 정보면 follow_up 금지·follow_up에는 question 필드 필수"
            ),
        ),
    }


def _part_label(exam_part: str) -> str:
    return "필기" if exam_part == "written" else "실기"


def _base_tags(exam_part: str) -> list[str]:
    return ["정처기", _part_label(exam_part)]


# ─────────────────────────────────────────────
# 샘플 생성
# ─────────────────────────────────────────────

def _c5_plan(case: C5PlanCase, *, today: date) -> dict[str, Any]:
    todos = [
        {"title": t, "due_date": today.isoformat(), "tags": _base_tags(case.exam_part) + ["오늘"]}
        for t in case.today_tasks
    ]
    calendar_events = [
        {
            "title": title,
            "due_date": (today + timedelta(days=offset)).isoformat(),
            "tags": _base_tags(case.exam_part) + ["미래"],
        }
        for offset, title in case.future_events
    ]
    calendar_events.append(
        {
            "title": f"정처기 {_part_label(case.exam_part)} 시험",
            "due_date": (today + timedelta(days=case.horizon_days)).isoformat(),
            "tags": _base_tags(case.exam_part) + ["시험"],
        }
    )
    return {
        "summary_text": (
            f"정처기 {_part_label(case.exam_part)} D-{case.horizon_days} 플랜입니다. "
            "오늘 할 일은 todos에, 이후 일정은 calendar_events에 분리했습니다."
        ),
        "todos": todos,
        "calendar_events": calendar_events,
    }


def _c5_sample(info: dict, case: C5PlanCase, *, today: date, variant: int) -> dict[str, Any]:
    plan = _c5_plan(case, today=today)
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
            "id": f"ipe-v3-c5-{case.case_id}-{variant + 1:03d}",
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-v3-hardening",
            "provenance": PROVENANCE,
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": f"정보처리기사 {_part_label(case.exam_part)}",
            "exam_part": case.exam_part,
            "time_left_days": case.horizon_days,
            "hardening_targets": ["c5_branch", "todos_today_only", "calendar_future"],
        },
    }


def _route_plan(case: PlanRouteCase, *, today: date) -> dict[str, Any]:
    todos = [
        {"title": t, "due_date": today.isoformat(), "tags": _base_tags(case.exam_part) + ["오늘"]}
        for t in case.today_tasks
    ]
    calendar_events = [
        {
            "title": title,
            "due_date": (today + timedelta(days=offset)).isoformat(),
            "tags": _base_tags(case.exam_part) + ["미래"],
        }
        for offset, title in case.future_tasks
    ]
    calendar_events.append(
        {
            "title": f"정처기 {_part_label(case.exam_part)}",
            "due_date": (today + timedelta(days=case.horizon_days)).isoformat(),
            "tags": _base_tags(case.exam_part) + ["시험"],
        }
    )
    return {
        "summary_text": (
            f"정처기 {_part_label(case.exam_part)} 준비 플랜입니다. "
            f"충분한 정보가 있으므로 {case.weak_area} 보완 중심으로 바로 계획합니다."
        ),
        "todos": todos,
        "calendar_events": calendar_events,
    }


def _route_sample(info: dict, case: PlanRouteCase, *, today: date, variant: int) -> dict[str, Any]:
    plan = _route_plan(case, today=today)
    parsed = parse_plan(json.dumps(plan, ensure_ascii=False))
    errors = check_plan_consistency(parsed, today=today, horizon_days=case.horizon_days)
    if errors:
        raise ValueError(f"route {case.case_id}: {errors}")
    all_suffixes = PLAN_ROUTE_SUFFIXES + _date_suffixes(today)
    suffix = all_suffixes[variant % len(all_suffixes)]
    return {
        "messages": [
            _system(today.isoformat()),
            {"role": "user", "content": f"{case.user}{suffix}"},
            {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)},
        ],
        "meta": {
            "id": f"ipe-v3-route-{case.case_id}-{variant + 1:03d}",
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-v3-hardening",
            "provenance": PROVENANCE,
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": f"정보처리기사 {_part_label(case.exam_part)}",
            "exam_part": case.exam_part,
            "time_left_days": case.horizon_days,
            "weak_subjects": [case.weak_area],
            "hardening_targets": ["route_plan", "no_followup_when_sufficient"],
        },
    }


def _followup_sample(info: dict, case: FollowUpCase, *, today: date, variant: int) -> dict[str, Any]:
    assistant = {
        "kind": "follow_up",
        "question": case.question,
        "missing_aspects": list(case.missing_aspects),
    }
    suffix = FOLLOWUP_SUFFIXES[variant % len(FOLLOWUP_SUFFIXES)]
    return {
        "messages": [
            _system(today.isoformat()),
            {"role": "user", "content": f"{case.user}{suffix}"},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": {
            "id": f"ipe-v3-fu-{case.case_id}-{variant + 1:02d}",
            "domain": "exam",
            "kind": "follow_up",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-v3-hardening",
            "provenance": "exam-follow-up-synth",
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": "정보처리기사",
            "hardening_targets": ["followup_question_field", "single_json"],
        },
    }


# ─────────────────────────────────────────────
# 메인 빌드
# ─────────────────────────────────────────────

def build_samples(
    info: dict[str, Any],
    *,
    today: str,
    c5_total: int,
    route_total: int,
    followup_total: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for i in range(c5_total):
        today_i = date.fromisoformat(DATE_POOL[i % len(DATE_POOL)])
        rows.append(_c5_sample(info, C5_CASES[i % len(C5_CASES)], today=today_i, variant=i))

    for i in range(route_total):
        today_i = date.fromisoformat(DATE_POOL[i % len(DATE_POOL)])
        rows.append(_route_sample(info, PLAN_ROUTE_CASES[i % len(PLAN_ROUTE_CASES)], today=today_i, variant=i))

    for i in range(followup_total):
        today_i = date.fromisoformat(DATE_POOL[i % len(DATE_POOL)])
        rows.append(_followup_sample(info, FOLLOWUP_CASES[i % len(FOLLOWUP_CASES)], today=today_i, variant=i))

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="postcheck v3 실패 유형 보강 SFT 생성")
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO)
    parser.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--today", default=DEFAULT_TODAY)
    parser.add_argument("--c5-total", type=int, default=60)
    parser.add_argument("--route-total", type=int, default=60)
    parser.add_argument("--followup-total", type=int, default=60)
    args = parser.parse_args()

    samples = build_samples(
        _load_info(args.info),
        today=args.today,
        c5_total=args.c5_total,
        route_total=args.route_total,
        followup_total=args.followup_total,
    )
    write_jsonl(samples, args.out_path)
    print(f"wrote {len(samples)} v3 hardening samples -> {args.out_path}")
    c5_n = sum(1 for s in samples if "c5_branch" in s["meta"].get("hardening_targets", []))
    route_n = sum(1 for s in samples if "no_followup_when_sufficient" in s["meta"].get("hardening_targets", []))
    fu_n = sum(1 for s in samples if s["meta"].get("kind") == "follow_up")
    print(f"  c5_branch: {c5_n}, route_plan: {route_n}, follow_up_schema: {fu_n}")


if __name__ == "__main__":
    main()
