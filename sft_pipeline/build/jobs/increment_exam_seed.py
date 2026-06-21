"""정보처리기사 지식 기반 exam SFT seed 증분 생성 CLI.

공식 시험 정보와 후기 패턴 요약을 원천 데이터로 분리해 두고, 기존
`sft_pipeline/data/seeds/exam.jsonl` 과 같은 `{messages, meta}` 포맷의
결정론적 샘플을 만든다. 외부 후기 원문은 저장하지 않고 요약 패턴만 사용한다.
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


DEFAULT_INFO_PATH = Path("sft_pipeline/data/exam_info/information_processing_engineer.json")
DEFAULT_SEED_PATH = Path("sft_pipeline/data/seeds/exam.jsonl")
DEFAULT_OUT_PATH = Path("sft_pipeline/data/generated/exam_information_processing_engineer.jsonl")


SYSTEM_PROMPT = (
    "너는 사용자의 일정·계획 요청을 구체적이고 실행 가능한 플랜으로 변환하는 AI 플래너다. "
    "기준일은 __TODAY__이다. 출력은 반드시 JSON만 사용한다.\n"
    "출력 규칙: 범위 밖(주식·요리·날씨 등) → out_of_scope / 잡담(인사·감사·감정) → chit_chat / "
    "정보 부족 → follow_up(질문 1개, 최대 2회 후 가정으로 plan) / 충분 → plan\n"
    "필수 수집: 여행(기간·목적) / 시험(유형·시험일·진도·가용시간) / 과제(마감·분량) / "
    "루틴(시작일·빈도·분량)\n"
    "스키마—\n"
    "out_of_scope: {\"kind\":\"out_of_scope\",\"message\":\"안내\"}\n"
    "chit_chat: {\"kind\":\"chit_chat\",\"message\":\"응답+플랜유도\"}\n"
    "follow_up: {\"kind\":\"follow_up\",\"question\":\"질문1개\",\"missing_aspects\":[\"부족\"]}\n"
    "plan: {\"kind\":\"plan\",\"title\":\"제목(30자)\",\"deadline\":\"YYYY-MM-DD\",\"assumptions\":[],"
    "\"phases\":[{\"phase\":\"단계명\",\"due_date\":\"YYYY-MM-DD\",\"tasks\":[{\"title\":\"할일(20자)\","
    "\"due_date\":\"YYYY-MM-DD\",\"priority\":\"high|medium|low\",\"tags\":[]}]}],\"calendar_events\":[],"
    "\"summary_text\":\"2~3문장\"}\n"
    "품질: 마감 역산·하루 2~4 task·정확한 시험 과목명 사용·합격 기준은 공식 정보와 일치"
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no} JSON 파싱 실패: {exc}") from exc
    return rows


def _iso(today: date, days: int) -> str:
    return (today + timedelta(days=days)).isoformat()


def _system(today: date) -> dict[str, str]:
    return {"role": "system", "content": SYSTEM_PROMPT.replace("__TODAY__", today.isoformat())}


def _task(title: str, due: str, priority: str, tags: list[str]) -> dict[str, Any]:
    return {"title": title, "due_date": due, "priority": priority, "tags": tags}


def _make_plan_case(info: dict[str, Any], pattern: dict[str, Any], today: date) -> dict[str, Any]:
    part = info["exam_parts"][pattern["part"]]
    deadline = _iso(today, int(pattern["time_left_days"]))
    is_written = pattern["part"] == "written"

    if is_written:
        subjects = part["subjects"]
        weak_subjects = subjects[2:]
        user = (
            f"{pattern['time_left_days']}일 후 정보처리기사 필기 시험이야. 하루 {pattern['daily_hours']}시간 가능하고 "
            f"{pattern['start_level']} 상태야. 목표는 {pattern['goal']}이고, "
            f"{', '.join(weak_subjects)}가 약해."
        )
        title = f"정처기 필기 {pattern['time_left_days']}일 준비"
        phases = [
            {
                "phase": "공식 과목·기준 확인",
                "due_date": _iso(today, 1),
                "tasks": [
                    _task("5개 필기 과목 범위 확인", _iso(today, 0), "high", ["정처기", "필기"]),
                    _task("과락 기준 40점 체크", _iso(today, 1), "high", ["정처기", "합격기준"]),
                ],
            },
            {
                "phase": "기출 회독·약점 보완",
                "due_date": _iso(today, max(2, int(pattern["time_left_days"]) - 3)),
                "tasks": [
                    _task("데이터베이스구축 오답 정리", _iso(today, 2), "high", ["정처기", "DB"]),
                    _task("프로그래밍언어활용 풀이", _iso(today, 3), "high", ["정처기", "프로그래밍"]),
                    _task("정보시스템구축관리 암기", _iso(today, 4), "medium", ["정처기", "보안"]),
                ],
            },
            {
                "phase": "실전 점검",
                "due_date": _iso(today, int(pattern["time_left_days"]) - 1),
                "tasks": [
                    _task("100문항 모의고사 풀기", _iso(today, int(pattern["time_left_days"]) - 2), "high", ["정처기", "모의고사"]),
                    _task("과목별 40점 미만 점검", _iso(today, int(pattern["time_left_days"]) - 1), "high", ["정처기", "오답"]),
                ],
            },
        ]
        summary = (
            f"필기는 {', '.join(subjects)} 5과목이고, 과목당 40점 이상·평균 60점 이상이 기준입니다. "
            "남은 기간에는 모든 내용을 넓게 보기보다 약점 과목 과락 방지와 기출 회독을 우선했습니다."
        )
    else:
        areas = part["study_areas"]
        user = (
            f"{pattern['time_left_days']}일 후 정보처리기사 실기야. 하루 {pattern['daily_hours']}시간 가능하고 "
            f"{pattern['start_level']} 상태야. 목표는 {pattern['goal']}이야."
        )
        title = f"정처기 실기 {pattern['time_left_days']}일 준비"
        phases = [
            {
                "phase": "실기 핵심 범위 압축",
                "due_date": _iso(today, 3),
                "tasks": [
                    _task("정보처리실무 범위 확인", _iso(today, 0), "high", ["정처기", "실기"]),
                    _task("SQL 응용 문제 풀이", _iso(today, 1), "high", ["정처기", "SQL"]),
                    _task("프로그래밍언어활용 풀이", _iso(today, 2), "high", ["정처기", "프로그래밍"]),
                ],
            },
            {
                "phase": "서술형·키워드 반복",
                "due_date": _iso(today, max(4, int(pattern["time_left_days"]) - 3)),
                "tasks": [
                    _task("테스트 관리 키워드 암기", _iso(today, 4), "medium", ["정처기", "테스트"]),
                    _task("개발 보안 키워드 정리", _iso(today, 5), "medium", ["정처기", "보안"]),
                    _task("요구사항 확인 서술 연습", _iso(today, 6), "medium", ["정처기", "서술형"]),
                ],
            },
            {
                "phase": "최종 실전",
                "due_date": _iso(today, int(pattern["time_left_days"]) - 1),
                "tasks": [
                    _task("실기 모의답안 작성", _iso(today, int(pattern["time_left_days"]) - 2), "high", ["정처기", "실기"]),
                    _task("빈출 키워드 최종 복습", _iso(today, int(pattern["time_left_days"]) - 1), "high", ["정처기", "복습"]),
                ],
            },
        ]
        summary = (
            f"실기는 {part['subject']} 한 과목이며 100점 만점 60점 이상이 기준입니다. "
            f"{', '.join(areas[:4])} 같은 넓은 범위 중 점수화가 쉬운 SQL·프로그래밍·키워드 암기를 먼저 배치했습니다."
        )

    assistant = {
        "kind": "plan",
        "title": title,
        "deadline": deadline,
        "assumptions": [],
        "phases": phases,
        "calendar_events": [{"title": part["name"], "due_date": deadline, "tags": ["시험", "정처기"]}],
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
            "scenario": f"{part['name']} {pattern['time_left_days']}일 {pattern['result']} 후기 기반",
            "source": "official-info+review-pattern",
            "exam_code": info["exam_code"],
            "exam_part": pattern["part"],
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
        "question": "정보처리기사 필기인지 실기인지와 하루 공부 가능 시간을 알려주세요.",
        "missing_aspects": ["시험 유형(필기/실기)", "하루 가용 시간"],
    }
    return {
        "messages": [
            _system(today),
            {"role": "user", "content": "다음 주 정처기 준비 계획 짜줘"},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": {
            "id": "ipe-followup-missing-part-hours",
            "domain": "exam",
            "kind": "follow_up",
            "turn_type": "single",
            "today": today.isoformat(),
            "scenario": "정보처리기사 유형·가용시간 미확인",
            "source": "official-info+gold-seed",
            "exam_code": info["exam_code"],
            "official_sources": [source["url"] for source in info["official_sources"]],
        },
    }


def build_samples(info: dict[str, Any], today: date) -> list[dict[str, Any]]:
    samples = [_make_followup_case(info, today)]
    samples.extend(_make_plan_case(info, pattern, today) for pattern in info["review_patterns"])
    return samples


def _dedupe_by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        row_id = str(row.get("meta", {}).get("id") or json.dumps(row["messages"], ensure_ascii=False))
        if row_id in seen:
            continue
        seen.add(row_id)
        deduped.append(row)
    return deduped


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 exam seed JSONL 증분 생성")
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO_PATH)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument("--today", type=date.fromisoformat, default=date(2026, 6, 9))
    parser.add_argument("--append-to-seed", action="store_true", help="기존 exam.jsonl 뒤에 중복 없이 병합해 덮어쓴다")
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
