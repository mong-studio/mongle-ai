"""structured_opic.csv → 오픽 전용 plan_generator(days) SFT jsonl.

공용 templates.build_plan 은 정처기(필기) 공부 흐름(개념→기출→오답)을 만든다.
오픽(말하기)에는 맞지 않으므로, assistant 의 days 콘텐츠만 오픽 실제 공부
흐름(설문→오픽노잼→스크립트→모의고사→실전 점검)으로 만든다.

학습 == 서빙: system/user/parsed_goal 은 plan_generator_template 의 런타임 미러를
그대로 재사용해 서빙 계약과 바이트 동일하게 유지하고, days 만 오픽용으로 채운다.
서빙 plan_generator 계약(2026-06 기준):
- 출력 스키마: {summary_text, days:[{date, tasks:[{title, due_date}]}], personalization_patch}
  (difficulty·rationale 없음, 키 순서 summary_text→days→personalization_patch)
- 오늘부터 30일 이내, 하루 1~3 task, 전체 15개 이하, 각 task.due_date == day.date
- title 은 실행 기준(횟수·강도·점검)을 드러내고 "연습/준비" 같은 포괄 표현 금지
- 마감(시험)일이 30일 이내면 그날 실제 행동("OPIc 시험 응시")을 배치
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sft_pipeline.build.lib.plan_generator_template import (
    PLAN_GENERATOR_SYSTEM,
    _as_jsonable,
    build_parsed_goal,
    plan_generator_user,
)
from sft_pipeline.io_utils import write_jsonl

_HORIZON_DAYS = 30
_MAX_TASKS = 15


def _series(goal: str) -> str:
    """목표 등급 → 오픽노잼 시리즈 라벨."""
    g = (goal or "").upper()
    return "IH" if ("AL" in g or "IH" in g) else "IM"


def _prep_pool(case: dict) -> list[str]:
    """오픽 준비 태스크 순서 풀(개념→설문→입력→스크립트→연습→모의고사→점검).

    서빙 규칙: title 에 횟수·강도·점검 기준을 넣고 "연습/준비" 같은 포괄 표현은 피한다.
    케이스별 약점은 자유 텍스트라 title(≤20자)로 자르면 깨져서 summary_text 로만 전한다.
    """
    series = _series(case.get("goal", ""))
    return [
        "오픽 등급·시험 형식 파악",
        "배경 설문 12항목 선택",
        f"오픽노잼 {series} 5강 시청",
        "주제별 스토리 5개 작성",
        "빈출 4유형 답변 녹음",
        "여우오픽 모의고사 1회 풀이",
        "돌발 질문 5개 답변 정리",
        "취약 주제 3회 반복 녹음",
        "필러·발화 흐름 점검",
    ]


def _spread_offsets(n: int, last: int) -> list[int]:
    """prep task n개를 [0, last] 구간에 흐름대로 분산(앞쪽 개념·뒤쪽 점검)."""
    if n <= 1:
        return [0]
    return [round(i * last / (n - 1)) for i in range(n)]


def build_days(case: dict, today: date) -> list[dict[str, Any]]:
    try:
        tld = int(case.get("time_left_days") or 0)
    except (ValueError, TypeError):
        tld = 0
    if tld <= 0:
        tld = 7

    exam_in_horizon = tld <= _HORIZON_DAYS
    last_prep = (tld - 1) if exam_in_horizon else (_HORIZON_DAYS - 1)
    last_prep = max(last_prep, 0)

    cap = _MAX_TASKS - (1 if exam_in_horizon else 0)  # 시험 task 1칸 확보
    prep_count = min(len(_prep_pool(case)), max(1, tld * 2), cap)
    prep_tasks = _prep_pool(case)[:prep_count]

    # 분산 배치(하루 ≤3, 날짜 중복 시 다음 빈 날로 이동).
    by_off: dict[int, list[str]] = {}
    for title, off in zip(prep_tasks, _spread_offsets(len(prep_tasks), last_prep)):
        while len(by_off.get(off, [])) >= 3 and off < last_prep:
            off += 1
        by_off.setdefault(off, []).append(title)

    days: list[dict[str, Any]] = []
    for off in sorted(by_off):
        d = (today + timedelta(days=off)).isoformat()
        days.append({"date": d, "tasks": [{"title": t, "due_date": d} for t in by_off[off]]})

    if exam_in_horizon:
        exam_d = (today + timedelta(days=tld)).isoformat()
        days.append({"date": exam_d, "tasks": [{"title": "OPIc 시험 응시", "due_date": exam_d}]})
    return days


def build_summary(case: dict) -> str:
    """이장님 말투(해요체) 요약(≤1500). 케이스의 실제 전략을 자연스럽게 녹인다."""
    period = (case.get("time_left") or "").strip() or "남은 기간"
    daily = (case.get("daily_hours") or "").strip()
    goal = (case.get("goal") or "목표 등급").strip()
    series = _series(goal)
    daily_part = f"하루 {daily} 정도면 " if daily else ""
    note = (case.get("special_notes") or "").split(",")[0].strip()
    note_part = f" 특히 {note} 부분을 더 신경 써서 반복해봐요." if note else ""
    return (
        f"{period} 동안 {daily_part}{goal} 충분히 노려볼 만해요. "
        f"먼저 오픽노잼 {series} 시리즈로 감을 잡고 배경 설문과 주제별 아웃라인을 "
        f"준비한 다음, 여우오픽 모의고사와 돌발 대비로 실전 감각을 올리는 흐름으로 짰어요."
        f"{note_part}"
    )[:1500]


def build_record(case: dict, today: date) -> dict[str, Any]:
    parsed_goal = build_parsed_goal(case, today)
    user = plan_generator_user(parsed_goal=_as_jsonable(parsed_goal), today=today)
    assistant = {
        "summary_text": build_summary(case),
        "days": build_days(case, today),
        "personalization_patch": {"preferences": [], "constraints": [], "planning_style": []},
    }
    return {
        "messages": [
            {"role": "system", "content": PLAN_GENERATOR_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": {
            "provenance": "exam-crawl",
            "node": "plan_generator",
            "turn_type": "single",
            "exam_type": case.get("exam_type", ""),
            "result": (case.get("result") or "").strip(),
            "goal": (case.get("goal") or "").strip(),
            "today": today.isoformat(),
            "source_url": case.get("source_url", ""),
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description="structured_opic.csv → 오픽 plan_generator SFT")
    p.add_argument("structured_path", type=Path)
    p.add_argument("out_path", type=Path)
    p.add_argument("--today", type=date.fromisoformat, default=None)
    args = p.parse_args()

    today = args.today or date.today()
    with open(args.structured_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("[입력] structured.csv 가 비었습니다.")
    write_jsonl([build_record(c, today) for c in rows], args.out_path)
    print(f"wrote {len(rows)} 오픽 plan_generator samples -> {args.out_path}")


if __name__ == "__main__":
    main()
