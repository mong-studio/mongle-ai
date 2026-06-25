"""exam-synth 6종(필기/실기) → plan_generator(days) SFT jsonl.

exam_synth.build_seeds 의 조합 시드를 그대로 재사용하되, 출력은 옛 PlanOutput 이
아니라 런타임 days 계약으로 만든다(공용 build_assistant/build_parsed_goal 재사용).
exam-synth 6종(정처기필기·토익·한능검·SQLD·컴활1/2급)은 모두 기출-반복형이라
공용 templates 의 '개념→기출→오답→점검' 콘텐츠가 도메인상 맞다(OPIc 같은 말하기
도메인만 별도 생성기가 필요하다 — build_opic_plan_sft.py).

학습 == 서빙: system/user/parsed_goal/assistant 는 plan_generator_template 의 런타임
미러를 그대로 쓴다. provenance 만 exam-synth(저작권 안전·공개 허용)로 둔다.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from sft_pipeline.build.lib.exam_synth import EXAM_STRATEGY, build_seeds
from sft_pipeline.build.lib.plan_generator_template import (
    PLAN_GENERATOR_SYSTEM,
    _as_jsonable,
    build_assistant,
    build_parsed_goal,
    plan_generator_user,
)
from sft_pipeline.io_utils import write_jsonl


def _seed_to_case(seed: dict) -> dict[str, Any]:
    """exam_synth 시드 → 공용 build_* 가 읽는 case dict(구조화 CSV 컬럼과 동형)."""
    days = int(seed["days_left"])
    hours = seed["daily_hours"]
    return {
        "exam_type": seed["exam_type"],
        "goal": seed["goal"],
        "time_left_days": days,
        "time_left": f"D-{days}",
        "daily_hours": f"{hours}시간",
        "daily_hours_value": hours,
        "start_level": seed["level"],
        "special_notes": seed["note"],
        "actual_plan_summary": EXAM_STRATEGY.get(seed["exam_type"], ""),
        "source_url": "",
    }


def build_record(seed: dict, today: date) -> dict[str, Any]:
    case = _seed_to_case(seed)
    parsed_goal = build_parsed_goal(case, today)
    user = plan_generator_user(parsed_goal=_as_jsonable(parsed_goal), today=today)
    assistant = build_assistant(case, today)  # 공용 days 콘텐츠(기출-반복형, 6종 적합)
    return {
        "messages": [
            {"role": "system", "content": PLAN_GENERATOR_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": {
            "provenance": "exam-synth",
            "node": "plan_generator",
            "turn_type": "single",
            "exam_type": seed["exam_type"],
            "time_left_days": int(seed["days_left"]),
            "goal": seed["goal"],
            "level": seed["level"],
            "note": seed["note"],
            "today": today.isoformat(),
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description="exam-synth → plan_generator(days) SFT")
    p.add_argument("out_path", type=Path)
    p.add_argument("--total", type=int, default=600, help="총 시드 수(6종 균등 분배)")
    p.add_argument("--today", type=date.fromisoformat, default=None)
    args = p.parse_args()

    today = args.today or date.today()
    seeds = build_seeds(args.total)
    write_jsonl([build_record(s, today) for s in seeds], args.out_path)
    print(f"wrote {len(seeds)} exam-synth plan_generator samples -> {args.out_path}")


if __name__ == "__main__":
    main()
