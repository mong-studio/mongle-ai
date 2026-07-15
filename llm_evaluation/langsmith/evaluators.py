from __future__ import annotations

import json
import math
import re
from datetime import date

from pydantic import TypeAdapter, ValidationError

from agents.todo_creation.schemas import PlannerResult

# 카나·한자·키릴 (한글/라틴/숫자/기호는 허용)
_FOREIGN = re.compile(r"[぀-ヿ一-鿿Ѐ-ӿ]")
_PLANNER_ADAPTER = TypeAdapter(PlannerResult)


def _r(key: str, score: int | None, comment: str = "") -> dict:
    return {"key": key, "score": score, "comment": comment}


def structure_valid(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """결과가 PlannerResult 유니온으로 파싱되는가 (TaskCandidate 필드 포함)."""
    try:
        _PLANNER_ADAPTER.validate_python(outputs["result"])
        return _r("structure_valid", 1)
    except ValidationError as err:
        return _r("structure_valid", 0, str(err)[:300])


def routing_correct(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """category가 기대하는 kind로 라우팅됐는가."""
    expected = reference_outputs.get("expected_kind")
    actual = outputs.get("kind")
    return _r("routing_correct", int(actual == expected), f"expected={expected} actual={actual}")


def date_sanity(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """candidates의 모든 due_date가 today 이후인가."""
    if outputs.get("kind") != "candidates":
        return _r("date_sanity", None, "n/a")
    today = date.fromisoformat(inputs["today"])
    items = outputs["result"].get("todos", []) + outputs["result"].get("calendar_events", [])
    bad = [i["due_date"] for i in items if date.fromisoformat(i["due_date"]) < today]
    return _r("date_sanity", int(not bad), f"past_due={bad}")


def korean_only(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """렌더되는 텍스트 필드에 외국어(카나·한자·키릴) 누출이 없는가."""
    res = outputs["result"]
    texts: list[str] = []
    if outputs.get("kind") == "candidates":
        for i in res.get("todos", []) + res.get("calendar_events", []):
            texts.append(i.get("title", ""))
            texts.extend(i.get("tags", []))
    elif outputs.get("kind") == "follow_up":
        texts.append(res.get("question", ""))
    elif outputs.get("kind") == "out_of_scope":
        texts.append(res.get("message", ""))
    leaked = [t for t in texts if _FOREIGN.search(t)]
    return _r("korean_only", int(not leaked), f"leaked={leaked}")


def frontend_contract(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """mongle-web 렌더에 필요한 필드를 다 담는가 (계약 수준).

    candidates: todos/calendar_events 리스트 + 각 항목 title/due_date/tags.
    follow_up: question. out_of_scope: message.
    """
    kind = outputs.get("kind")
    res = outputs["result"]
    if kind == "candidates":
        for key in ("todos", "calendar_events"):
            if not isinstance(res.get(key), list):
                return _r("frontend_contract", 0, f"missing list: {key}")
        for i in res["todos"] + res["calendar_events"]:
            if not all(k in i for k in ("title", "due_date", "tags")):
                return _r("frontend_contract", 0, f"task missing fields: {i}")
        return _r("frontend_contract", 1)
    if kind == "follow_up":
        return _r("frontend_contract", int(bool(res.get("question"))))
    if kind == "out_of_scope":
        return _r("frontend_contract", int(bool(res.get("message"))))
    return _r("frontend_contract", 0, f"unknown kind: {kind}")


def plan_density(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """candidates 플랜이 마감까지 기간 대비 충분한 항목 밀도를 가지는가.

    성긴 플랜(빈 날이 많음)을 낮게 채점한다. 대략 3일당 1개를 기준선으로,
    최소 3개를 기대한다(expected = max(3, ceil(horizon/3))). non-candidates 는 n/a.
    """
    if outputs.get("kind") != "candidates":
        return _r("plan_density", None, "n/a")
    res = outputs["result"]
    items = res.get("todos", []) + res.get("calendar_events", [])
    n = len(items)
    if n == 0:
        return _r("plan_density", 0.0, "empty plan")
    today = date.fromisoformat(inputs["today"])
    dues = [date.fromisoformat(i["due_date"]) for i in items if i.get("due_date")]
    horizon = (max(dues) - today).days + 1 if dues else 1
    expected = max(3, math.ceil(max(horizon, 1) / 3))
    score = round(min(1.0, n / expected), 2)
    return _r("plan_density", score, f"items={n} horizon={horizon}d expected>={expected}")


def plan_split(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """candidates 가 적절히 나뉘었는가 (plan-coherence Gate 2 구조).

    역할 분리: 오늘 마감→todos, 미래→calendar_events. 제목 중복(같은 항목 중복 배치) 금지.
    3개 체크의 평균(0~1). non-candidates 는 n/a.
    """
    if outputs.get("kind") != "candidates":
        return _r("plan_split", None, "n/a")
    today = date.fromisoformat(inputs["today"])
    res = outputs["result"]
    todos = res.get("todos", [])
    events = res.get("calendar_events", [])
    todos_today = all(date.fromisoformat(t["due_date"]) == today for t in todos)
    events_future = all(date.fromisoformat(e["due_date"]) > today for e in events)
    titles = [i.get("title") for i in todos + events]
    no_dup = len(titles) == len(set(titles))
    checks = [todos_today, events_future, no_dup]
    fails = [
        name
        for name, ok in zip(("todo!=today", "calendar<=today", "dup_title"), checks)
        if not ok
    ]
    return _r("plan_split", round(sum(checks) / len(checks), 2), ",".join(fails) or "ok")


HEURISTIC_EVALUATORS = [
    structure_valid, routing_correct, date_sanity, korean_only, frontend_contract,
    plan_density, plan_split,
]


def _history_from_turns(prev_turns: list[str]) -> list[dict]:
    # ponytail: assistant 응답을 저장하지 않으므로 이전 턴을 user 발화로만 재구성.
    #           judge_sufficiency는 사용자 발화 누적으로 충분성을 판단하므로 충분.
    return [{"role": "user", "content": t} for t in prev_turns]


def make_judge_evaluators(judge) -> list:
    """기존 judge_sufficiency 를 재사용하는 LLM 평가자 2종을 만든다.

    plan_justified: 플랜을 낸 example에서 judge가 '정보 충분'이라고 보면 1
                    (충분치 않은데 플랜을 냈으면 0 — 성급한 플랜).
    followup_needed: 꼬리질문을 던진 example에서 judge도 '정보 부족'이라 보면 1
                    (충분한데 되물었으면 0 — 불필요한 꼬리질문).
    """

    async def plan_justified(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
        if outputs.get("kind") != "candidates":
            return _r("plan_justified", None, "n/a (non-plan)")
        turns = inputs["turns"]
        sufficient, missing, _goal = await judge.judge_sufficiency(
            history=_history_from_turns(turns[:-1]),
            message=turns[-1],
            today=date.fromisoformat(inputs["today"]),
            user_profile_memory=inputs.get("user_profile_memory"),
        )
        return _r("plan_justified", int(sufficient), f"judge_missing={missing}")

    async def followup_needed(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
        if outputs.get("kind") != "follow_up":
            return _r("followup_needed", None, "n/a (non-followup)")
        turns = inputs["turns"]
        sufficient, missing, _goal = await judge.judge_sufficiency(
            history=_history_from_turns(turns[:-1]),
            message=turns[-1],
            today=date.fromisoformat(inputs["today"]),
            user_profile_memory=inputs.get("user_profile_memory"),
        )
        return _r("followup_needed", int(not sufficient), f"judge_missing={missing}")

    return [plan_justified, followup_needed]


_PLAN_QUALITY_SYS = (
    "너는 플랜 품질 평가자다. 사용자 목표와 날짜별 플랜을 보고 아래 3개를 1~5점으로 채점한다.\n"
    "- m1 분배 합리성: 기계적 균등분할이 아니라 난이도·맥락을 반영했는가\n"
    "- m3 순서 논리: 선행→후행 의존(기초 학습 후 심화·복습)이 지켜지는가\n"
    "- m4 완결성: 이 플랜대로 하면 목표가 실제로 달성되는가\n"
    "JSON 객체 하나만 출력. 스키마: {\"m1\": 1~5, \"m3\": 1~5, \"m4\": 1~5}"
)

_PLAN_QUALITY_SCHEMA = {
    "type": "object",
    "properties": {
        "m1": {"type": "integer"},
        "m3": {"type": "integer"},
        "m4": {"type": "integer"},
    },
    "required": ["m1", "m3", "m4"],
}


def make_plan_quality_evaluator(judge):
    """candidates 의 의미적 분할 품질(plan-coherence Gate 3)을 LLM 으로 채점.

    judge.complete_raw 에 루브릭+guided_json 으로 m1/m3/m4(1~5)를 받아 평균을 0~1 로 정규화.
    새 외부 모델 없이 기존 ports LLM 재사용.
    """

    async def plan_quality(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
        if outputs.get("kind") != "candidates":
            return _r("plan_quality", None, "n/a")
        res = outputs["result"]
        goal = " / ".join(inputs.get("turns") or [])
        items = res.get("todos", []) + res.get("calendar_events", [])
        plan_text = "; ".join(f"{i.get('due_date')} {i.get('title')}" for i in items)
        messages = [
            {"role": "system", "content": _PLAN_QUALITY_SYS},
            {
                "role": "user",
                "content": f"목표: {goal}\n플랜: {plan_text}\n요약: {res.get('summary_text', '')}",
            },
        ]
        raw = await judge.complete_raw(
            messages=messages, label="validate_plan", guided_json=_PLAN_QUALITY_SCHEMA
        )
        try:
            parsed = json.loads(raw)
            scores = [int(parsed[k]) for k in ("m1", "m3", "m4")]
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            return _r("plan_quality", None, f"parse fail: {str(raw)[:60]}")
        avg = sum(scores) / len(scores)
        return _r(
            "plan_quality",
            round((avg - 1) / 4, 2),
            f"m1={scores[0]} m3={scores[1]} m4={scores[2]}",
        )

    return plan_quality
