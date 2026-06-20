"""토익(TOEIC) 지식 기반 exam SFT seed 증분 생성 CLI.

`increment_exam_seed.py`(정보처리기사)와 같은 방법으로, 공식 시험 정보와 후기 패턴
요약을 원천 데이터(`sft_pipeline/data/exam_info/toeic.json`)로 분리해 두고, 기존
`sft_pipeline/data/seeds/exam.jsonl` 과 같은 `{messages, meta}` 포맷의 결정론적
샘플을 만든다. 외부 후기 원문은 저장하지 않고 요약 패턴만 사용한다.

정보처리기사와 달리 토익은 필기/실기가 아니라 LC(Part1~4)·RC(Part5~7) 구성의
점수형 시험(990점 만점, LC 495 + RC 495)이라, 플랜 템플릿을 LC/RC 약점 중심으로
구성한다. 시스템 프롬프트·직렬화 헬퍼는 increment_exam_seed 의 단일 정의를
재사용해 학습 템플릿 정합성(train/inference skew 방지)을 유지한다.
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

from sft_pipeline.build.jobs.increment_exam_seed import (
    _dedupe_by_id,
    _iso,
    _load_json,
    _read_jsonl,
    _system,
    _task,
    _write_jsonl,
)

DEFAULT_INFO_PATH = Path("sft_pipeline/data/exam_info/toeic.json")
DEFAULT_SEED_PATH = Path("sft_pipeline/data/seeds/exam.jsonl")
DEFAULT_OUT_PATH = Path("sft_pipeline/data/generated/exam_toeic.jsonl")

VALID_PARTS = {"listening", "reading", "overall"}


def _format_facts(info: dict[str, Any]) -> str:
    """summary_text 에 박을 공식 구성 한 문장(990점 만점·LC/RC·총문항)."""
    fmt = info["exam_format"]
    lc = info["exam_parts"]["listening"]
    rc = info["exam_parts"]["reading"]
    return (
        f"토익은 LC {lc['question_count']}·RC {rc['question_count']} 총 "
        f"{fmt['total_questions']}문항이고, {fmt['max_score']}점 만점"
        f"(LC {lc['max_score']} + RC {rc['max_score']})입니다."
    )


def _listening_phases(pattern: dict[str, Any], today: date) -> list[dict[str, Any]]:
    horizon = int(pattern["time_left_days"])
    return [
        {
            "phase": "공식 구성·약점 파트 확인",
            "due_date": _iso(today, 1),
            "tasks": [
                _task("토익 LC 파트 구성 확인", _iso(today, 0), "high", ["토익", "LC"]),
                _task("Part2 질의응답 패턴 정리", _iso(today, 1), "high", ["토익", "Part2"]),
            ],
        },
        {
            "phase": "쉐도잉·받아쓰기 청취 보완",
            "due_date": _iso(today, max(2, horizon - 3)),
            "tasks": [
                _task("Part3·4 받아쓰기 훈련", _iso(today, 2), "high", ["토익", "받아쓰기"]),
                _task("Part3·4 쉐도잉 반복", _iso(today, 3), "high", ["토익", "쉐도잉"]),
                _task("빈출 패러프레이징 정리", _iso(today, 4), "medium", ["토익", "단어"]),
            ],
        },
        {
            "phase": "실전 LC 점검",
            "due_date": _iso(today, horizon - 1),
            "tasks": [
                _task("모의 LC 한 세트 풀기", _iso(today, horizon - 2), "high", ["토익", "모의고사"]),
                _task("오답 파트 집중 복습", _iso(today, horizon - 1), "high", ["토익", "오답"]),
            ],
        },
    ]


def _reading_phases(pattern: dict[str, Any], today: date) -> list[dict[str, Any]]:
    horizon = int(pattern["time_left_days"])
    return [
        {
            "phase": "공식 구성·약점 파트 확인",
            "due_date": _iso(today, 1),
            "tasks": [
                _task("토익 RC 파트 구성 확인", _iso(today, 0), "high", ["토익", "RC"]),
                _task("Part5 문법 포인트 점검", _iso(today, 1), "high", ["토익", "Part5"]),
            ],
        },
        {
            "phase": "문법·독해 속도 보완",
            "due_date": _iso(today, max(2, horizon - 3)),
            "tasks": [
                _task("Part5 문법 집중 풀이", _iso(today, 2), "high", ["토익", "문법"]),
                _task("Part7 독해 속도 훈련", _iso(today, 3), "high", ["토익", "Part7"]),
                _task("Part7 풀이 순서 정하기", _iso(today, 4), "medium", ["토익", "시간배분"]),
            ],
        },
        {
            "phase": "실전 RC 점검",
            "due_date": _iso(today, horizon - 1),
            "tasks": [
                _task("모의 RC 시간 배분 연습", _iso(today, horizon - 2), "high", ["토익", "모의고사"]),
                _task("오답 유형 집중 복습", _iso(today, horizon - 1), "high", ["토익", "오답"]),
            ],
        },
    ]


def _overall_phases(pattern: dict[str, Any], today: date) -> list[dict[str, Any]]:
    horizon = int(pattern["time_left_days"])
    return [
        {
            "phase": "공식 구성·목표 점수 확인",
            "due_date": _iso(today, 1),
            "tasks": [
                _task("토익 200문항 구조 확인", _iso(today, 0), "high", ["토익", "구성"]),
                _task("목표 점수 환산표 점검", _iso(today, 1), "high", ["토익", "목표"]),
            ],
        },
        {
            "phase": "LC·RC 약점 병행 보완",
            "due_date": _iso(today, max(2, horizon - 3)),
            "tasks": [
                _task("Part3·4 받아쓰기 훈련", _iso(today, 2), "high", ["토익", "LC"]),
                _task("Part5 문법 집중 풀이", _iso(today, 3), "high", ["토익", "RC"]),
                _task("Part7 독해·빈출 단어", _iso(today, 4), "medium", ["토익", "단어"]),
            ],
        },
        {
            "phase": "실전 모의고사 점검",
            "due_date": _iso(today, horizon - 1),
            "tasks": [
                _task("ETS 공식 모의고사 풀기", _iso(today, horizon - 2), "high", ["토익", "모의고사"]),
                _task("시간 배분·오답 점검", _iso(today, horizon - 1), "high", ["토익", "오답"]),
            ],
        },
    ]


_PHASE_BUILDERS = {
    "listening": _listening_phases,
    "reading": _reading_phases,
    "overall": _overall_phases,
}

_PART_LABEL = {"listening": "LC", "reading": "RC", "overall": "LC·RC 전체"}
_PART_WEAK = {
    "listening": "LC(청취) Part3·4",
    "reading": "RC(독해) Part5·7",
    "overall": "LC·RC 전반",
}


def _make_plan_case(info: dict[str, Any], pattern: dict[str, Any], today: date) -> dict[str, Any]:
    part = pattern["part"]
    if part not in VALID_PARTS:
        raise ValueError(f"unknown toeic part {part!r} (expected one of {sorted(VALID_PARTS)})")
    horizon = int(pattern["time_left_days"])
    deadline = _iso(today, horizon)

    user = (
        f"{horizon}일 후 토익 시험이야. 하루 {pattern['daily_hours']}시간 가능하고 "
        f"{pattern['start_level']} 상태야. 목표는 {pattern['goal']}이고, "
        f"{_PART_WEAK[part]}가 약해."
    )
    title = f"토익 {_PART_LABEL[part]} {horizon}일 준비"[:30]
    phases = _PHASE_BUILDERS[part](pattern, today)

    if part == "listening":
        focus = "LC는 Part2 패턴과 Part3·4 쉐도잉·받아쓰기로 청취력을 끌어올리는 데 집중했습니다."
    elif part == "reading":
        focus = "RC는 Part5 문법과 Part7 독해 속도·시간 배분 훈련에 시간을 집중했습니다."
    else:
        focus = "약점 파트를 데이터로 확인해 LC·RC를 병행 보완하고 공식 모의고사로 컷을 점검했습니다."
    summary = f"{_format_facts(info)} 합격선이 없는 점수형 시험이라 {focus}"

    assistant = {
        "kind": "plan",
        "title": title,
        "deadline": deadline,
        "assumptions": [],
        "phases": phases,
        "calendar_events": [
            {"title": "토익 정기시험", "due_date": deadline, "tags": ["시험", "토익"]}
        ],
        "summary_text": summary,
    }
    return {
        "messages": [
            _system(today),
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": {
            "id": pattern["case_id"],
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "scenario": f"토익 {_PART_LABEL[part]} {horizon}일 {pattern['result']} 후기 기반",
            "source": "official-info+review-pattern",
            "exam_code": info["exam_code"],
            "exam_part": part,
            "result": pattern["result"],
            "reported_score": pattern["reported_score"],
            "time_left_days": pattern["time_left_days"],
            "daily_hours": pattern["daily_hours"],
            "official_sources": [source["url"] for source in info["official_sources"]],
            "study_process_summary": pattern["process"],
        },
    }


def _make_followup_case(info: dict[str, Any], today: date) -> dict[str, Any]:
    assistant = {
        "kind": "follow_up",
        "question": "토익 시험일과 하루 공부 가능 시간, 현재 점수(또는 모의고사 점수)를 알려주세요.",
        "missing_aspects": ["시험일", "하루 가용 시간", "현재 점수"],
    }
    return {
        "messages": [
            _system(today),
            {"role": "user", "content": "다음 달 토익 준비 계획 짜줘"},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": {
            "id": "toeic-followup-missing-date-hours-score",
            "domain": "exam",
            "kind": "follow_up",
            "turn_type": "single",
            "today": today.isoformat(),
            "scenario": "토익 시험일·가용시간·현재점수 미확인",
            "source": "official-info+gold-seed",
            "exam_code": info["exam_code"],
            "official_sources": [source["url"] for source in info["official_sources"]],
        },
    }


def build_samples(info: dict[str, Any], today: date) -> list[dict[str, Any]]:
    samples = [_make_followup_case(info, today)]
    samples.extend(_make_plan_case(info, pattern, today) for pattern in info["review_patterns"])
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="토익 exam seed JSONL 증분 생성")
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO_PATH)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument("--today", type=date.fromisoformat, default=date(2026, 6, 14))
    parser.add_argument(
        "--append-to-seed",
        action="store_true",
        help="기존 exam.jsonl 뒤에 중복 없이 병합해 덮어쓴다",
    )
    args = parser.parse_args()

    info = _load_json(args.info)
    new_samples = build_samples(info, args.today)

    if args.append_to_seed:
        merged = _dedupe_by_id([*_read_jsonl(args.seed), *new_samples])
        _write_jsonl(merged, args.seed)
        print(f"merged {len(new_samples)} generated samples -> {args.seed} (total={len(merged)})")
        return

    _write_jsonl(copy.deepcopy(new_samples), args.out)
    print(f"wrote {len(new_samples)} generated samples -> {args.out}")


if __name__ == "__main__":
    main()
