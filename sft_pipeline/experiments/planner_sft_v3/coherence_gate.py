"""3단 게이트 중 Gate 2 구조 불변식(결정론) — evaluating-plan-coherence 루브릭.

위반은 침묵 교정하지 않고 사유 문자열로 반환한다(스펙 §5).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from adapters.todo_creation.qwen_llm import is_korean_reply

# 비시험 목표 플랜에 나타나면 S4 위반인 시험 어휘 (지난 실패: lifestyle→정처기 붕괴)
EXAM_LEAK_TERMS: tuple[str, ...] = (
    "기출", "모의고사", "필기시험", "실기시험", "시험 응시", "오답", "수험",
    "정보처리기사", "정처기", "토익", "오픽", "자격증",
)

_ENGLISH_RUN = re.compile(r"[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})+")  # 연속 영단어 2개 이상

_MAX_DAYS = 30
_MAX_TASKS = 15
_MAX_TASKS_PER_DAY = 3
_CADENCE = re.compile(r"주\s*(\d+)\s*회")


def has_english_leak(text: str) -> bool:
    return bool(_ENGLISH_RUN.search(text))


def _all_titles(plan: dict[str, Any]) -> list[str]:
    return [
        str(task.get("title") or "")
        for day in plan.get("days", [])
        for task in day.get("tasks", [])
    ]


def check_structure(plan: dict[str, Any], parsed_goal: dict[str, Any], today: date) -> list[str]:
    issues: list[str] = []
    days = plan.get("days", [])
    deadline = date.fromisoformat(parsed_goal["deadline"]) if parsed_goal.get("deadline") else None

    # S2 시간 논리
    if len(days) > _MAX_DAYS:
        issues.append(f"S2: days {len(days)}개 > {_MAX_DAYS}")
    titles = _all_titles(plan)
    if len(titles) > _MAX_TASKS:
        issues.append(f"S2: task {len(titles)}개 > {_MAX_TASKS}")
    for day in days:
        try:
            day_date = date.fromisoformat(str(day.get("date")))
        except ValueError:
            issues.append(f"S2: 날짜 형식 위반 {day.get('date')!r}")
            continue
        if day_date < today or (deadline and day_date > deadline):
            issues.append(f"S2: {day_date} 이 기간(today~deadline) 밖")
        for task in day.get("tasks", []):
            if str(task.get("due_date")) != str(day.get("date")):
                issues.append(f"S2: due_date {task.get('due_date')} != day {day.get('date')}")

    # S3 부하 상한
    for day in days:
        if len(day.get("tasks", [])) > _MAX_TASKS_PER_DAY:
            issues.append(f"S3: {day.get('date')} 에 task {len(day['tasks'])}개 > {_MAX_TASKS_PER_DAY}")

    # S4 참조 무결성 — summary 포함 전체 텍스트 검사 (스킬: summary 도 S4 대상)
    full_text = " ".join(titles) + " " + str(plan.get("summary_text") or "")
    if parsed_goal.get("plan_kind") != "exam":
        for term in EXAM_LEAK_TERMS:
            if term in full_text:
                issues.append(f"S4: 비시험 목표에 시험 어휘 '{term}' 혼입")
                break
    if has_english_leak(full_text):
        issues.append("S4: 근거 없는 연속 영어 혼입")
    if not is_korean_reply(full_text):
        issues.append("S4: 한국어 응답 아님")

    # S5 분량 보존 — routine 의 '주 N회' 만 결정론 검사 (그 외 도메인은 판정 불가 → 통과)
    if parsed_goal.get("plan_kind") == "routine":
        slots_text = " ".join(str(v) for v in (parsed_goal.get("slots") or {}).values())
        match = _CADENCE.search(slots_text)
        if match and days:
            weekly = int(match.group(1))
            first_day = date.fromisoformat(str(days[0]["date"]))
            week_end = first_day + timedelta(days=6)
            first_week = sum(
                len(d.get("tasks", []))
                for d in days
                if first_day <= date.fromisoformat(str(d["date"])) <= week_end
            )
            if first_week < weekly:
                issues.append(f"S5: 주 {weekly}회 요구인데 첫 주 {first_week}회 배치")

    # 중복 배치 금지
    seen: set[tuple[str, str]] = set()
    for day in days:
        for task in day.get("tasks", []):
            key = (str(task.get("title")), str(task.get("due_date")))
            if key in seen:
                issues.append(f"중복 배치: {key}")
            seen.add(key)
    return issues


SEMANTIC_JUDGE_SYSTEM = """당신은 일정 계획의 논리성을 채점하는 심사자다.
사용자 목표와 계획(JSON)을 보고 아래 4개 차원을 각각 1~5 정수로 채점한다.

- M1 분배 합리성: "1일차, 2일차…" 식 기계적 균등 분할이 아니라 난이도와 맥락을 반영해 배분했는가
- M2 시간 현실성: 항목당 부하가 현실적이고 무리한 몰아넣기가 없는가
- M3 순서 논리: 선행→후행 의존을 지키는가 (점검은 실행 후, 기초는 심화 전)
- M4 완결성: 이 계획대로 하면 사용자 목표가 실제로 달성되는가

반드시 아래 JSON 형식으로만 답한다. 설명·서술 금지.
{"M1": <1~5>, "M2": <1~5>, "M3": <1~5>, "M4": <1~5>}"""


def semantic_judge_user(plan: dict[str, Any], parsed_goal: dict[str, Any]) -> str:
    return (
        f"[사용자 목표]\n{parsed_goal.get('goal_text')}"
        f" (유형: {parsed_goal.get('plan_kind')})\n\n"
        f"[계획]\n{json.dumps(plan, ensure_ascii=False)}"
    )


def parse_judge_reply(text: str) -> dict[str, Any]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge JSON 파싱 실패: {exc}") from exc
    scores = {}
    for key in ("M1", "M2", "M3", "M4"):
        value = raw.get(key)
        if not isinstance(value, int) or not 1 <= value <= 5:
            raise ValueError(f"{key} 점수 범위 위반: {value!r}")
        scores[key] = value
    scores["average"] = round(sum(scores.values()) / 4, 2)
    return scores


def verdict(parse_ok: bool, structure_issues: list[str], semantic_avg: float | None) -> str:
    """스펙 §5 판정 규칙. 구조 위반은 의미 점수로 희석하지 않는다."""
    if not parse_ok or structure_issues:
        return "DROP"
    if semantic_avg is None or semantic_avg < 3.0:
        return "DROP"
    if semantic_avg < 4.0:
        return "FIX"
    return "ACCEPT"
