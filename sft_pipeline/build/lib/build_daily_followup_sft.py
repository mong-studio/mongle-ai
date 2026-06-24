"""저정보 일상 입력 → 꼬리질문 답변 후 judge(충분) 멀티턴 레코드(D9: ≤2턴).

런타임 재진입 미러(planner.py): 단일 judge 레코드 — message=원본 저정보 요청,
history=[{assistant:질문},{user:답변}] 가 user content 에 내재. follow_up 노드는
별도 시스템 프롬프트라 여기 섞지 않는다(train==serve).
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from agents.todo_creation.planner.slot_schemas import slot_hints
from sft_pipeline.build.lib.daily_nodes_template import build_judge_record
from sft_pipeline.build.lib.planner_nodes_template import (
    PLANNER_JUDGE_SYSTEM,
    planner_judge_user,
)
from sft_pipeline.io_utils import write_jsonl

_MAX_FOLLOWUPS = 2  # D9
# 비운 슬롯 key → structured_daily 컬럼(저정보 입력·사용자 답변 구성용).
_COL_FOR = {"activity": "activity", "cadence": "cadence", "goal": "goal_text"}


def _withhold(case: dict, withheld: list[str]) -> dict:
    blanked = dict(case)  # 불변: 새 dict
    for slot in withheld:
        blanked[_COL_FOR.get(slot, slot)] = ""
    return blanked


def build_multiturn_record(case: dict, *, withheld: list[str], today: date) -> dict[str, Any]:
    ask = withheld[:_MAX_FOLLOWUPS]
    low_info = _withhold(case, ask)
    initial = str(low_info.get("goal_text") or low_info.get("activity") or "계획 짜줘")

    # 봇 꼬리질문(여러 슬롯 한 질문에 묶음, D9). ?로 끝나야 _follow_up_count 가 센다.
    question = " / ".join(slot_hints(case.get("plan_kind"), ask)) + " 알려주세요?"
    answer = ", ".join(str(case.get(_COL_FOR.get(s, s), "")) for s in ask)
    history = [
        {"role": "assistant", "content": question},
        {"role": "user", "content": answer},
    ]
    user = planner_judge_user(
        history=history, message=initial, today=today, user_profile_memory=None
    )
    # 답변 후 judge 는 충분(full case) — daily_nodes_template 의 judge assistant 재사용.
    assistant = build_judge_record(case, today)["messages"][-1]["content"]

    return {
        "messages": [
            {"role": "system", "content": PLANNER_JUDGE_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
        "meta": {
            "provenance": "daily-crawl",
            "node": "judge",
            "turn_type": "multi",
            "plan_kind": case.get("plan_kind", ""),
            "today": today.isoformat(),
            "source_url": case.get("source_url", ""),
            "missing_aspects": ask,
        },
    }


def build_samples(structured_path: Path, today: date) -> list[dict]:
    with open(structured_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    samples: list[dict] = []
    for case in rows:
        # routine 케이스에서 cadence 를 비운 저정보 시드(가장 흔한 미충족 슬롯).
        if case.get("plan_kind") == "routine" and case.get("cadence"):
            samples.append(build_multiturn_record(case, withheld=["cadence"], today=today))
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="structured_daily.csv → 멀티턴 judge jsonl")
    parser.add_argument("structured_path", type=Path)
    parser.add_argument("out_path", type=Path)
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    samples = build_samples(args.structured_path, args.today or date.today())
    if not samples:
        raise SystemExit("[입력] 생성된 멀티턴 샘플이 0개입니다.")
    write_jsonl(samples, args.out_path)


if __name__ == "__main__":
    main()
