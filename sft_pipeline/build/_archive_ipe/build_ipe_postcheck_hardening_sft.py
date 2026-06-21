"""postcheck v2 실패 유형을 겨냥한 정보처리기사 SFT 보강 샘플 생성."""

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
DEFAULT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_postcheck_hardening_sft.jsonl")
DEFAULT_TODAY = "2026-06-09"
PROVENANCE = "exam-synth"


@dataclass(frozen=True)
class PlanRouteCase:
    case_id: str
    exam_part: str
    user: str
    weak_area: str
    horizon_days: int
    today_tasks: tuple[str, ...]
    future_tasks: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class FollowUpSchemaCase:
    case_id: str
    user: str
    question: str
    missing_aspects: tuple[str, ...]


PLAN_CASES: tuple[PlanRouteCase, ...] = (
    PlanRouteCase(
        "plan-no-followup-written",
        "written",
        "정처기 필기 7일 남았고 하루 3시간 가능해. 4과목과 5과목이 약해. 목표는 합격이야.",
        "프로그래밍언어활용, 정보시스템구축관리",
        7,
        ("약점 범위 확정", "과락 기준 확인"),
        ((1, "4과목 기출 풀이"), (3, "5과목 오답 정리"), (6, "최종 모의 풀이")),
    ),
    PlanRouteCase(
        "plan-no-followup-practical",
        "practical",
        "정처기 실기 10일 남았어. SQL과 프로그래밍이 약하고 하루 4시간 가능해.",
        "SQL 응용, 프로그래밍 언어 활용",
        10,
        ("SQL 약점 확인", "답안 형식 점검"),
        ((1, "SQL 기출 풀이"), (5, "코드 추적 연습"), (9, "실전 답안 복습")),
    ),
    PlanRouteCase(
        "plan-c5-short",
        "written",
        "정처기 필기 14일 남았어. 하루 2시간, 데이터베이스가 약해. 바로 계획만 JSON으로 줘.",
        "데이터베이스구축",
        14,
        ("DB 약점 표시", "오늘 기출 배치"),
        ((2, "DB 기출 풀이"), (7, "전과목 모의고사"), (13, "오답 최종 복습")),
    ),
    PlanRouteCase(
        "plan-retry",
        "practical",
        "실기 불합격했고 30일 뒤 재시험이야. 보안과 SQL이 약해. 하루 2.5시간 가능해.",
        "소프트웨어 보안, SQL 응용",
        30,
        ("불합격 원인 정리", "약점 우선순위 정하기"),
        ((7, "보안 기출 풀이"), (15, "SQL 반복 풀이"), (29, "최종 오답 점검")),
    ),
)


FOLLOWUP_CASES: tuple[FollowUpSchemaCase, ...] = (
    FollowUpSchemaCase(
        "followup-question-part-date",
        "정보처리기사 준비 계획 세워줘.",
        "필기와 실기 중 어떤 시험을 준비 중이고, 시험일은 언제인가요?",
        ("시험 유형", "시험일"),
    ),
    FollowUpSchemaCase(
        "followup-question-hours-level",
        "정처기 실기 3주 계획 만들어줘.",
        "현재 실기 진도와 하루 공부 가능 시간을 알려주세요.",
        ("현재 진도", "하루 가용 시간"),
    ),
    FollowUpSchemaCase(
        "followup-question-date",
        "정처기 따고 싶은데 일정 잡아줘.",
        "시험일 또는 남은 기간을 알려주세요.",
        ("시험일 또는 남은 기간",),
    ),
    FollowUpSchemaCase(
        "followup-question-goal",
        "정보처리기사 필기 공부 루틴 짜줘.",
        "시험일까지 남은 기간과 목표 점수 또는 목표 결과를 알려주세요.",
        ("시험일까지 남은 기간", "목표"),
    ),
)


PLAN_SUFFIXES = (
    "",
    " 충분한 정보가 있으니 follow_up 하지 말고 plan만 출력해줘.",
    " JSON 하나만 출력하고 코드블록은 붙이지 마.",
    " tags는 한국어로만 써줘.",
    " todos에는 오늘 날짜만 넣어줘.",
    " 미래 일정은 calendar_events에만 넣어줘.",
    " 날짜 오타 없이 YYYY-MM-DD로 써줘.",
    " title은 20자 안으로 써줘.",
    " 질문하지 말고 바로 실행 계획을 만들어줘.",
    " 이미 필요한 정보는 다 줬으니 추가 질문은 하지 마.",
    " follow_up 대신 summary_text/todos/calendar_events를 출력해줘.",
    " 오늘 할 일과 시험일까지의 일정을 분리해줘.",
    " 영문 태그 대신 한국어 태그만 사용해줘.",
    " due_date는 네 자리 연도부터 정확히 써줘.",
    " JSON 앞뒤에 설명을 붙이지 마.",
    " 코드펜스 없이 순수 JSON만 줘.",
    " 시험일을 calendar_events에 넣어줘.",
    " 오늘 날짜가 아닌 할 일은 todos에 넣지 마.",
    " 각 일정의 태그에는 정처기와 필기/실기를 넣어줘.",
    " 과목명은 한국어 공식 명칭으로 써줘.",
    " 계획 외 다른 텍스트는 출력하지 마.",
    " 날짜는 기준일 2026-06-09 이후로만 써줘.",
    " 시험일까지 범위를 넘기지 말아줘.",
    " 플랜 JSON 하나로만 답해줘.",
)

FOLLOWUP_SUFFIXES = (
    "",
    " 질문은 question 필드에 넣어줘.",
    " message만 쓰지 말고 question을 반드시 포함해줘.",
    " missing_aspects도 배열로 넣어줘.",
    " JSON 하나만 출력해줘.",
    " question과 missing_aspects만으로 부족 정보를 물어봐줘.",
    " kind는 follow_up으로 고정해줘.",
    " 추가 설명 대신 질문 하나만 만들어줘.",
    " 부족한 정보만 짧게 물어봐줘.",
    " 코드블록 없이 순수 JSON으로만 답해줘.",
)


def _load_info(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _system(today: str) -> dict[str, str]:
    return {
        "role": "system",
        "content": runtime_system_prompt(
            today,
            extra_quality=(
                "충분한 시험 정보가 있으면 follow_up 금지·JSON 하나만 출력·"
                "follow_up에는 question 필드 필수"
            ),
        ),
    }


def _tags(case: PlanRouteCase, extra: str) -> list[str]:
    part = "필기" if case.exam_part == "written" else "실기"
    return ["정처기", part, extra]


def _plan(case: PlanRouteCase, *, today: date) -> dict[str, Any]:
    todos = [
        {"title": title, "due_date": today.isoformat(), "tags": _tags(case, "오늘")}
        for title in case.today_tasks
    ]
    calendar_events = [
        {
            "title": title,
            "due_date": (today + timedelta(days=offset)).isoformat(),
            "tags": _tags(case, "미래"),
        }
        for offset, title in case.future_tasks
    ]
    part_name = "필기" if case.exam_part == "written" else "실기"
    calendar_events.append(
        {
            "title": f"정처기 {part_name}",
            "due_date": (today + timedelta(days=case.horizon_days)).isoformat(),
            "tags": _tags(case, "시험"),
        }
    )
    return {
        "summary_text": (
            f"정보처리기사 {part_name} 준비 플랜입니다. 충분한 정보가 있으므로 "
            f"추가 질문 없이 {case.weak_area} 보완 중심으로 계획합니다."
        ),
        "todos": todos,
        "calendar_events": calendar_events,
    }


def _plan_sample(info: dict[str, Any], case: PlanRouteCase, *, today: date, variant: int) -> dict[str, Any]:
    plan = _plan(case, today=today)
    parsed = parse_plan(json.dumps(plan, ensure_ascii=False))
    errors = check_plan_consistency(parsed, today=today, horizon_days=case.horizon_days)
    if errors:
        raise ValueError(f"{case.case_id}: invalid postcheck hardening plan {errors}")
    return {
        "messages": [
            _system(today.isoformat()),
            {"role": "user", "content": f"{case.user}{PLAN_SUFFIXES[variant % len(PLAN_SUFFIXES)]}"},
            {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)},
        ],
        "meta": {
            "id": f"ipe-postcheck-plan-{case.case_id}-{variant + 1:02d}",
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-postcheck-hardening",
            "provenance": PROVENANCE,
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": "정보처리기사 필기" if case.exam_part == "written" else "정보처리기사 실기",
            "exam_part": case.exam_part,
            "time_left_days": case.horizon_days,
            "weak_subjects": [case.weak_area],
            "hardening_targets": ["route_plan", "single_json", "iso_date", "korean_tags", "c5_branching"],
        },
    }


def _followup_sample(info: dict[str, Any], case: FollowUpSchemaCase, *, today: date, variant: int) -> dict[str, Any]:
    assistant = {
        "kind": "follow_up",
        "question": case.question,
        "missing_aspects": list(case.missing_aspects),
    }
    return {
        "messages": [
            _system(today.isoformat()),
            {"role": "user", "content": f"{case.user}{FOLLOWUP_SUFFIXES[variant % len(FOLLOWUP_SUFFIXES)]}"},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": {
            "id": f"ipe-postcheck-followup-{case.case_id}-{variant + 1:02d}",
            "domain": "exam",
            "kind": "follow_up",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "synthetic-postcheck-hardening",
            "provenance": "exam-follow-up-synth",
            "exam_code": info.get("exam_code", "information_processing_engineer"),
            "exam_type": "정보처리기사",
            "hardening_targets": ["followup_question_field", "single_json"],
        },
    }


def build_samples(info: dict[str, Any], *, today: str, plan_total: int, followup_total: int) -> list[dict[str, Any]]:
    today_date = date.fromisoformat(today)
    rows: list[dict[str, Any]] = []
    for i in range(plan_total):
        rows.append(_plan_sample(info, PLAN_CASES[i % len(PLAN_CASES)], today=today_date, variant=i // len(PLAN_CASES)))
    for i in range(followup_total):
        rows.append(
            _followup_sample(
                info,
                FOLLOWUP_CASES[i % len(FOLLOWUP_CASES)],
                today=today_date,
                variant=i // len(FOLLOWUP_CASES),
            )
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="postcheck 실패 유형 보강 SFT 생성")
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO)
    parser.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--today", default=DEFAULT_TODAY)
    parser.add_argument("--plan-total", type=int, default=96)
    parser.add_argument("--followup-total", type=int, default=40)
    args = parser.parse_args()

    samples = build_samples(
        _load_info(args.info),
        today=args.today,
        plan_total=args.plan_total,
        followup_total=args.followup_total,
    )
    write_jsonl(samples, args.out_path)
    print(f"wrote {len(samples)} postcheck hardening samples -> {args.out_path}")


if __name__ == "__main__":
    main()
