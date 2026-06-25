"""exam 케이스 → 런타임 plan_generator 노드 계약의 (system, user, assistant) 트리플.

학습 == 서빙을 위해, 서빙 노드(`adapters/todo_creation/_prompts.py` 의
PLAN_GENERATOR_SYSTEM / plan_generator_user)와 **바이트 동일한** system·user 를
만든다. 런타임 코드를 직접 import 하면 학습 파이프라인↔런타임이 결합되므로
(plan_schemas 와 동일 정책) 여기서 미러하고, 동기화는 테스트로 보호한다:
tests/test_plan_generator_template.py::test_mirror_matches_runtime.

assistant 타깃은 결정론적으로 만든다(teacher LLM 불필요). 전략 구조는 기존
templates.build_plan 을 재사용하고, plan_generator 서빙 계약(최대 7일·하루
1~3 task·전체 12개 이하·due_date==day.date)에 맞춰 days 스키마로 reshape 한다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from sft_pipeline.build.lib.templates import _field, build_plan

# 서빙 plan_generator 가 만드는 최대 계획 일수(런타임 PLAN_GENERATOR_SYSTEM 규칙).
_HORIZON_DAYS = 30
_MAX_TASKS = 15


# --- 런타임 미러 (adapters/todo_creation/_prompts.py 와 동일해야 함) ----------

# ponytail: 런타임 PLAN_GENERATOR_SYSTEM 의 바이트 복사. 드리프트는 sync 테스트가 잡는다.
PLAN_GENERATOR_SYSTEM = """
너는 사용자의 목표를 날짜별 TODO/캘린더 후보로 만드는 한국어 플래너다.

[출력 규칙]
- 반드시 JSON 객체 하나만 출력한다.
- 마크다운, 코드펜스, 주석, 설명 문장을 출력하지 않는다.
- summary_text 와 days 를 먼저 출력하고 personalization_patch 는 마지막에 둔다.
- 스키마:
{
  "summary_text": "1500자 이하 플랜 요약",
  "days": [
    {
      "date": "YYYY-MM-DD",
      "tasks": [
        {"title": "20자 이하", "due_date": "YYYY-MM-DD"}
      ]
    }
  ],
  "personalization_patch": {"preferences": [], "constraints": [], "planning_style": []}
}

[규칙]
- 플랜 입력(JSON)의 goal_text, plan_kind, slots만 현재 목표의 근거로 사용한다.
- 도메인 지식이 없는 목표는 일반적인 실행 단계로 구성하되, 다른 시험이나 자격증 내용을 끌어오지 않는다.
- 도메인 지식이 부족해도 "조사/확인"만 나열하지 말고, 목표에 맞는 실행 단계를 만든다
  (일반 골격: 정보 조사 → 기초 다지기 → 점진적 강화/연습 → 최종 점검·리허설).
- 날짜는 시스템이 다시 배치하므로 단계 순서가 드러나는 임시 절대 날짜를 사용한다.
- title 은 20자 이하의 실제 행동 단위다.
- title 은 무엇을 어떤 기준으로 수행하는지 알 수 있게 쓴다. 가능한 경우 시간·거리·횟수·강도·점검 기준 중 하나를 포함한다.
- "훈련", "연습", "준비", "시작", "계획 세우기"처럼 실행 기준이 없는 포괄적인 title만 만들지 않는다.
- 같은 title을 반복하지 않는다. 반복 활동도 기초·기술·지구력·회복·점검처럼 단계와 목적이 드러나야 한다.
- 오늘부터 30일 이내의 핵심 단계만 만든다.
- 하루 tasks 는 1개 이상 3개 이하로 제한한다.
- 전체 tasks 는 15개 이하로 제한한다.
- days 의 각 date 는 서로 달라야 하고, 각 task 의 due_date 는 해당 day.date 와 같아야 한다.
- 같은 날짜를 반복하지 말고, 하루하루 다른 날짜로 펼친다.
- 오늘 날짜 task 는 TODO 후보, 미래 날짜 task 는 캘린더 후보가 된다.
- previous_plan 과 revision_request 가 있으면 이전 플랜을 수정 요청에 맞춰 재생성한다.
- 사용자가 말한 목표와 무관한 과목, 장소, 준비물을 임의로 만들지 않는다.
- 목표를 이해하기 어렵거나 필수 정보가 없으면 planner 단계에서 질문해야 하므로 여기서는 추측을 늘리지 않는다.
- 사용자가 말하지 않은 전문 지식이나 세부 범위를 아는 척하지 않는다. 필요한 정보가 없으면 planner 단계에서 질문해야 한다.
- 사용자가 목표일을 말하지 않았다면 시험일, 경기일, 마감일을 임의로 만들지 않는다.
- plan_kind가 exam이 아니면 시험, 필기, 실기, 기출, 자격증 과목을 절대 만들지 않는다.
- plan_kind=event 이면 훈련·회복·점검·경기 출전만 만든다.
- plan_kind=event 이고 목표일이 오늘부터 30일 이내면 마지막 날에 실제 경기/대회 출전 일정을 둔다.
- summary_text 는 친근한 이장님 말투로 짧게 설명한다.
- summary_text 는 따뜻한 해요체로 작성하고 '몽글'은 출력하지 않는다.
- tags 는 출력하지 않는다. 태그는 goal_tag 하나로 시스템이 일괄 적용한다.
- AI 답변 원문이나 전체 대화 로그를 personalization_patch 에 넣지 않는다.
- 마감일(시험일 등)이 오늘부터 30일 이내면, 그 날짜를 플랜의 마지막 날로 두고 마감 당일의 실제 행동을 배치한다.
- 실제 목표일이 30일 이후면 days에는 첫 30일 상세 일정만 만들고, 중간 점검이나 실제 목표일 일정을 넣지 않는다.
- 실제 목표일이 30일 이후면 첫 30일 뒤부터 목표일까지의 간단한 단계 흐름만 summary_text에 덧붙인다.
- 마감일 이후에는 어떤 task 도 만들지 않는다(회고·정리 등 포함).
- 날짜를 기계적으로 균등 분배하지 말고, 흐름에 맞게 배치한다(예: 개념 학습을 앞쪽에, 최종 점검을 마감 직전에).
- assumptions 가 있으면 어떤 정보를 가정했는지 summary_text 에 분명히 알린다.
"""


def _as_jsonable(value: Any) -> Any:
    """런타임 _as_jsonable 미러: JSON 라운드트립으로 date 등을 문자열화."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def plan_generator_user(*, parsed_goal: dict[str, Any], today: date) -> str:
    """런타임 plan_generator_user 미러. 서빙과 바이트 동일해야 한다."""
    return f"today={today.isoformat()}\n플랜 입력(JSON): {parsed_goal}"


# --- exam 케이스 → 노드 입출력 ------------------------------------------------


def _deadline(case: dict, today: date) -> date | None:
    try:
        days = int(case.get("time_left_days") or 0)
    except (ValueError, TypeError):
        days = 0
    return today + timedelta(days=days) if days > 0 else None


def _daily_capacity_minutes(case: dict) -> int | None:
    raw = case.get("daily_hours_value")
    try:
        hours = float(raw) if raw not in (None, "") else 0.0
    except (ValueError, TypeError):
        hours = 0.0
    return round(hours * 60) if hours > 0 else None


def build_parsed_goal(case: dict, today: date) -> dict[str, Any]:
    """exam 케이스 → 런타임 ParsedGoal 형태(서빙 judge 출력 미러)."""
    # ponytail: goal_tag 은 exam_type 공백 제거로 결정론 derive. judge LLM 불필요.
    exam = _field(case, "exam_type", default="")
    goal = _field(case, "goal", default="")
    goal_tag = exam.replace(" ", "") or goal.replace(" ", "") or "학습"
    deadline = _deadline(case, today)
    # slots: 사용자가 실제로 말한 값만(서빙 judge 규칙). 빈 값은 키를 넣지 않는다.
    slots = {
        k: v for k, v in (
            ("exam_name", exam),
            ("target", goal),
            ("start_level", (case.get("start_level") or "").strip()),
        ) if v
    }
    return {
        "intent": "plan",
        "plan_kind": "exam",
        "slots": slots,
        "goal_text": goal or exam or "학습 목표",
        "goal_tag": goal_tag,
        "deadline": deadline.isoformat() if deadline else None,
        "daily_capacity_minutes": _daily_capacity_minutes(case),
        "personalization_patch": {"preferences": [], "constraints": []},
    }


def _curve_difficulty(idx: int, total: int) -> int:
    """정렬 인덱스 → 난이도(1~3) 점증 곡선. 단일 task 는 보통(2)."""
    if total <= 1:
        return 2
    frac = idx / (total - 1)
    if frac < 0.34:
        return 1
    if frac < 0.67:
        return 2
    return 3


def build_plan_days(case: dict, today: date) -> list[dict[str, Any]]:
    """build_plan 전략을 재사용해 plan_generator days 스키마로 reshape.

    서빙 계약 준수: today 부터 최대 7일, 전체 task 12개 이하,
    각 task.due_date == 그 day.date, 같은 날짜 중복 없음.
    """
    plan = build_plan(case, today)
    horizon = today + timedelta(days=_HORIZON_DAYS - 1)
    tasks = sorted(
        (t for t in [*plan.todos, *plan.calendar_events] if t.due_date <= horizon),
        key=lambda t: t.due_date,
    )[:_MAX_TASKS]

    by_date: dict[date, list[dict[str, Any]]] = {}
    total = len(tasks)
    for idx, t in enumerate(tasks):
        by_date.setdefault(t.due_date, []).append(
            {
                "title": t.title,
                "due_date": t.due_date.isoformat(),
                # 난이도 곡선: 앞쪽(개념)은 쉽게, 마감(점검)으로 갈수록 점증(1→2→3).
                "difficulty": _curve_difficulty(idx, total),
            }
        )
    return [
        {"date": d.isoformat(), "tasks": items}
        for d, items in sorted(by_date.items())
    ]


def build_assistant(case: dict, today: date) -> dict[str, Any]:
    """plan_generator assistant 타깃 JSON 객체.

    서빙 스키마: summary_text → days → personalization_patch 순. task 는 {title,
    due_date}만(서빙은 difficulty/rationale 을 모델 출력에서 받지 않는다). difficulty 는
    build_plan_days 가 critic 용으로 들고 있으나 여기서 출력 전 제거한다.
    """
    plan = build_plan(case, today)
    days = [
        {
            "date": day["date"],
            "tasks": [
                {"title": t["title"], "due_date": t["due_date"]}
                for t in day["tasks"]
            ],
        }
        for day in build_plan_days(case, today)
    ]
    return {
        "summary_text": plan.summary_text,
        "days": days,
        "personalization_patch": {
            "preferences": [],
            "constraints": [],
            "planning_style": [],
        },
    }


def build_record(case: dict, today: date) -> dict[str, Any]:
    """exam 케이스 → plan_generator 노드 SFT 레코드(system/user/assistant)."""
    parsed_goal = build_parsed_goal(case, today)
    user = plan_generator_user(parsed_goal=_as_jsonable(parsed_goal), today=today)
    assistant = build_assistant(case, today)
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
            "today": today.isoformat(),
            "source_url": case.get("source_url", ""),
        },
    }
