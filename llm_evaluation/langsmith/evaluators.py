from __future__ import annotations

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


HEURISTIC_EVALUATORS = [
    structure_valid, routing_correct, date_sanity, korean_only, frontend_contract,
]
