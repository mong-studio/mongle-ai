"""재현용 라이브 스모크: 일상 목표 1건을 실제 RunPod planner 로 end-to-end.

clarify→generate→critique→backprompt 전 과정을 실제 LLM 으로 돌려 '정확한 답'을 본다.
.env 를 직접 로드하고 RunPodQwenLLM 을 직접 구성한다(AppConfig 전체 검증 우회).

2026-06-24 실행에서 비-시험 결함 2종 확인(슬롯 환각→clarification 건너뜀, lifestyle→시험
붕괴·critic 미탐지). 메모리 planner-live-nonexam-failures 참조. 유료 호출 주의.
실행: `uv run python scripts/live_planner_smoke.py` (.env 의 RUNPOD_* 필요).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    f = ROOT / ".env"
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _group_by_day(tasks):
    by: dict = {}
    for t in tasks:
        by.setdefault(t.due_date, []).append(t)
    return dict(sorted(by.items()))


async def main() -> None:
    _load_env()
    url = os.environ.get("RUNPOD_PLANNER_ENDPOINT_URL", "")
    key = os.environ.get("RUNPOD_API_KEY", "")
    if not url or not key:
        print("[중단] RUNPOD_PLANNER_ENDPOINT_URL / RUNPOD_API_KEY 없음")
        return
    print(f"[env] planner endpoint set={bool(url)} key set={bool(key)}")

    from adapters.todo_creation.runpod_llm import RunPodQwenLLM
    from agents.todo_creation.planner.pipeline import (
        PlannerPorts,
        get_debug_state,
        run,
    )
    from agents.todo_creation.schemas import PlannerInput

    llm = RunPodQwenLLM(endpoint_url=url, api_key=key, adapter="planner")
    ports = PlannerPorts(llm=llm)
    today = date.today()
    now = datetime.now()

    msg1 = "요즘 생활이 너무 불규칙한데 좀 잡아줘"
    print(f"\n=== turn1 (일상, 정보 부족 예상) ===\n사용자: {msg1}")
    first = await run(
        PlannerInput(user_id="live1", message=msg1, today=today, thread_id=None),
        ports=ports,
        now=now,
    )
    print(f"결과 타입: {type(first).__name__}")

    final = first
    if type(first).__name__ == "FollowUpResult":
        print(f"  되묻는 질문: {first.question}")
        print(f"  missing_aspects: {first.missing_aspects}")
        msg2 = "운동이랑 공부 위주로, 평일 저녁에 한 달 정도 할래"
        print(f"\n=== turn2 (답변 → 충분 예상) ===\n사용자: {msg2}")
        final = await run(
            PlannerInput(
                user_id="live1", message=msg2, today=today, thread_id=first.thread_id
            ),
            ports=ports,
            now=now,
        )
        print(f"결과 타입: {type(final).__name__}")

    if type(final).__name__ == "CandidatesResult":
        print("\n=== 최종 계획 (실제 생성·critic 통과본) ===")
        print(f"  summary: {final.summary_text}")
        tasks = list(final.todos) + list(final.calendar_events)
        for d, items in _group_by_day(tasks).items():
            load = sum(getattr(t, "difficulty", 1) for t in items)
            flag = "  ⚠️과부하" if load > 5 else ""
            print(f"  {d}: Σ{load}{flag}")
            for t in items:
                print(f"      - {t.title} (난이도 {getattr(t, 'difficulty', 1)})")
        st = get_debug_state(thread_id=final.thread_id, ports=ports)
        pg = st.get("parsed_goal", {})
        print(f"  parsed_goal.plan_kind: {pg.get('plan_kind')}")
        print(f"  parsed_goal.slots: {pg.get('slots')}")
        print(f"  parsed_goal.rationale: {pg.get('rationale')}")
    elif "OutOfScope" in type(final).__name__:
        print(f"  out_of_scope: {getattr(final, 'message', final)}")


if __name__ == "__main__":
    asyncio.run(main())
