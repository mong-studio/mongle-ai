"""structured_daily 케이스 → 일상 planner 노드 SFT 레코드(judge/goal_tag/generator/critic).

system 프롬프트는 런타임 미러 상수를 재사용한다(plan_kind 라우팅을 이미 담음).
판정은 런타임 slot_schemas.missing_required 를 직접 재사용 = train==serve.
generator 타깃은 현 런타임 계약(절대 날짜 days[], ≤7일·하루≤3·≤12)을 미러하되
내용은 추출된 real_breakdown 그대로(필러 잡무 합성 금지, §4.6).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from agents.todo_creation.planner.slot_schemas import missing_required
from sft_pipeline.build.lib.plan_critic_template import (
    PLAN_CRITIC_SYSTEM,
    _overloaded_days,
    plan_critic_user,
)
from sft_pipeline.build.lib.plan_generator_template import (
    PLAN_GENERATOR_SYSTEM,
    _as_jsonable,
    _curve_difficulty,
    plan_generator_user,
)
from sft_pipeline.build.lib.planner_nodes_template import (
    GOAL_TAG_SYSTEM,
    PLANNER_JUDGE_SYSTEM,
    goal_tag_user,
    planner_judge_user,
)

_HORIZON_DAYS = 7
_MAX_TASKS = 12

# structured_daily 컬럼 → slot_schemas 슬롯 key 매핑(plan_kind 별).
_SLOT_SOURCES: dict[str, dict[str, str]] = {
    "routine": {"activity": "activity", "cadence": "cadence"},
    "vague_goal": {"goal": "goal_text", "first_action": "activity", "weekly_cadence": "cadence"},
    "lifestyle": {"domains": "domains", "cadence_per_domain": "cadence", "horizon": "horizon_days"},
    "exam": {},
}


def daily_filled_slot_keys(case: dict) -> set[str]:
    sources = _SLOT_SOURCES.get(case.get("plan_kind", ""), {})
    return {slot for slot, col in sources.items() if str(case.get(col, "")).strip()}


def is_daily_sufficient(case: dict) -> tuple[bool, list[str]]:
    plan_kind = case.get("plan_kind", "")
    missing = missing_required(plan_kind, daily_filled_slot_keys(case))
    return (not missing), missing


def _slots_dict(case: dict) -> dict[str, str]:
    sources = _SLOT_SOURCES.get(case.get("plan_kind", ""), {})
    return {
        slot: str(case.get(col, "")).strip()
        for slot, col in sources.items()
        if str(case.get(col, "")).strip()
    }


def _goal_tag(case: dict) -> str:
    text = (case.get("goal_text") or case.get("activity") or "목표").strip()
    return text.replace(" ", "")[:20] or "목표"


def build_daily_parsed_goal(case: dict, today: date) -> dict[str, Any]:
    return {
        "intent": "plan",
        "plan_kind": case.get("plan_kind", ""),
        "slots": _slots_dict(case),
        "goal_text": case.get("goal_text") or case.get("activity") or "목표",
        "goal_tag": _goal_tag(case),
        "deadline": None,
        "daily_capacity_minutes": None,
        "personalization_patch": {"preferences": [], "constraints": []},
    }


def parse_real_breakdown(raw: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for chunk in (c.strip() for c in (raw or "").split(";") if c.strip()):
        parts = [p.strip() for p in chunk.split("|")]
        title = parts[0][:20] if parts else ""
        if not title:
            continue
        items.append(
            {
                "title": title,
                "cadence": parts[1] if len(parts) > 1 else "",
                "time_of_day": parts[2] if len(parts) > 2 else "",
            }
        )
    return items


def build_daily_days(case: dict, today: date) -> list[dict[str, Any]]:
    """real_breakdown 활동을 today 부터 하루 1개씩 펼친다(현 런타임 계약 준수).

    ponytail: 하루 1활동의 단순 펼침. real_breakdown 은 이미 활동 목록이라
    추가 분배가 불필요하고, 기계적 균등(critic coherence 위반)을 피한다.
    7일/12개 cap 초과분은 drop(silent-drop 경고는 빌더 진입점에서).
    """
    items = parse_real_breakdown(case.get("real_breakdown", ""))[:_MAX_TASKS]
    capped = items[:_HORIZON_DAYS]
    total = len(capped)
    days: list[dict[str, Any]] = []
    for idx, item in enumerate(capped):
        day = (today + timedelta(days=idx)).isoformat()
        days.append(
            {
                "date": day,
                "tasks": [
                    {
                        "title": item["title"],
                        "due_date": day,
                        "difficulty": _curve_difficulty(idx, total),
                    }
                ],
            }
        )
    return days


def _meta(case: dict, today: date, node: str, *, provenance: str = "daily-crawl") -> dict[str, Any]:
    return {
        "provenance": provenance,
        "node": node,
        "turn_type": "single",
        "plan_kind": case.get("plan_kind", ""),
        "today": today.isoformat(),
        "source_url": case.get("source_url", ""),
    }


def _synthetic_message(case: dict) -> str:
    slots = _slots_dict(case)
    slot_text = ", ".join(f"{k}={v}" for k, v in slots.items())
    base = case.get("goal_text") or case.get("activity") or ""
    return f"{base} ({slot_text})".strip()


def build_judge_record(case: dict, today: date) -> dict[str, Any]:
    sufficient, missing = is_daily_sufficient(case)
    parsed_goal = build_daily_parsed_goal(case, today)
    user = planner_judge_user(
        history=[], message=_synthetic_message(case), today=today, user_profile_memory=None
    )
    assistant = {
        "intent": "plan",
        "is_sufficient": sufficient,
        "missing_aspects": [] if sufficient else missing,
        "parsed_goal": _as_jsonable(parsed_goal),
    }
    return {
        "messages": [
            {"role": "system", "content": PLANNER_JUDGE_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": _meta(case, today, "judge"),
    }


def build_goal_tag_record(case: dict, today: date) -> dict[str, Any]:
    parsed_goal = build_daily_parsed_goal(case, today)
    user = goal_tag_user(parsed_goal=_as_jsonable(parsed_goal), history=[])
    assistant = {"goal_tag": parsed_goal["goal_tag"]}
    return {
        "messages": [
            {"role": "system", "content": GOAL_TAG_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": _meta(case, today, "goal_tag"),
    }


def build_generator_record(case: dict, today: date) -> dict[str, Any]:
    parsed_goal = build_daily_parsed_goal(case, today)
    user = plan_generator_user(parsed_goal=_as_jsonable(parsed_goal), today=today)
    days = build_daily_days(case, today)
    assistant = {
        "summary_text": f"'{parsed_goal['goal_text']}' 계획을 추출된 실제 활동대로 잡아뒀어요.",
        "rationale": "실제 후기에서 추출한 활동·빈도를 흐름에 맞게 배치하고 하루 부하를 분산했습니다."[:200],
        "personalization_patch": {"preferences": [], "constraints": [], "planning_style": []},
        "days": days,
    }
    return {
        "messages": [
            {"role": "system", "content": PLAN_GENERATOR_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": _meta(case, today, "generator"),
    }


def _critic_parsed_goal(case: dict, today: date) -> dict[str, Any]:
    return {**build_daily_parsed_goal(case, today), "plan_kind": case.get("plan_kind", "lifestyle")}


def _critic_record(case, today, *, plan, verdict, label) -> dict[str, Any]:
    parsed_goal = _critic_parsed_goal(case, today)
    user = plan_critic_user(
        parsed_goal=_as_jsonable(parsed_goal),
        plan_json=plan,
        today=today,
        overloaded_days=_overloaded_days(plan),
    )
    meta = _meta(case, today, "critic", provenance="daily-critic")
    meta["label"] = label
    return {
        "messages": [
            {"role": "system", "content": PLAN_CRITIC_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(verdict, ensure_ascii=False)},
        ],
        "meta": meta,
    }


def _inject_offgoal(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not plan:
        return plan
    poisoned = [dict(d) for d in plan]
    first = poisoned[0]
    first_tasks = list(first["tasks"])
    first_tasks.append({"title": "기출문제 2회분", "due_date": first["date"], "difficulty": 3})
    poisoned[0] = {**first, "tasks": first_tasks}
    return poisoned


def _inject_triviality(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fillers = ["운동복·신발 확인", "기구·장비 점검", "간식·음료 정리"]
    out: list[dict[str, Any]] = []
    for idx, day in enumerate(plan):
        tasks = [{**t, "title": fillers[idx % len(fillers)]} for t in day["tasks"]]
        out.append({**day, "tasks": tasks})
    return out


def build_critic_records(case: dict, today: date) -> list[dict[str, Any]]:
    clean = build_daily_days(case, today)
    if not clean:
        return []
    positive = _critic_record(
        case, today, plan=clean, verdict={"ok": True, "issues": []}, label="positive"
    )
    offgoal = _critic_record(
        case, today, plan=_inject_offgoal(clean),
        verdict={"ok": False, "issues": [{
            "day": None, "category": "coherence", "severity": "major",
            "detail": "목표와 무관한 시험 task 가 섞여 있다.",
            "suggested_fix": "목표 도메인에 맞는 활동만 남긴다.",
        }]},
        label="offgoal",
    )
    trivial = _critic_record(
        case, today, plan=_inject_triviality(clean),
        verdict={"ok": False, "issues": [{
            "day": None, "category": "coherence", "severity": "major",
            "detail": "준비·점검·정리 같은 잡무만 있고 실체 행동이 없다.",
            "suggested_fix": "실제 활동(운동·학습 등) 단위로 바꾼다.",
        }]},
        label="triviality",
    )
    return [positive, offgoal, trivial]


def build_records(case: dict, today: date) -> list[dict[str, Any]]:
    judge = build_judge_record(case, today)
    sufficient, _ = is_daily_sufficient(case)
    if not sufficient:
        return [judge]
    return [
        judge,
        build_goal_tag_record(case, today),
        build_generator_record(case, today),
        *build_critic_records(case, today),
    ]
