"""정보처리기사 크롤 결과를 SFT messages 데이터셋으로 구조화한다.

입력은 `crawl_results_*.jsonl` 이고, 출력은 두 가지다.

- 검수용 CSV: 준비 기간, 점수, 결과, 공부 과정 요약
- SFT JSONL: 기존 `data/seeds/exam.jsonl` 과 같은 `{messages, meta}` 포맷

저작권 안전을 위해 크롤 원문 전체는 SFT 출력에 포함하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


DEFAULT_CRAWL_PATH = Path("sft_pipeline/data/generated/crawl_results_information_processing_engineer.jsonl")
DEFAULT_INFO_PATH = Path("sft_pipeline/data/exam_info/information_processing_engineer.json")
DEFAULT_CSV_OUT = Path("sft_pipeline/data/generated/raw_cases_information_processing_engineer.csv")
DEFAULT_SFT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_sft.jsonl")


SYSTEM_PROMPT = (
    "너는 사용자의 일정·계획 요청을 구체적이고 실행 가능한 플랜으로 변환하는 AI 플래너다. "
    "기준일은 __TODAY__이다. 출력은 반드시 JSON만 사용한다.\n"
    "출력 규칙: 범위 밖(주식·요리·날씨 등) → out_of_scope / 잡담(인사·감사·감정) → chit_chat / "
    "정보 부족 → follow_up(질문 1개, 최대 2회 후 가정으로 plan) / 충분 → plan\n"
    "필수 수집: 시험(유형·시험일·진도·가용시간·목표)\n"
    "plan: {\"kind\":\"plan\",\"title\":\"제목(30자)\",\"deadline\":\"YYYY-MM-DD\",\"assumptions\":[],"
    "\"phases\":[{\"phase\":\"단계명\",\"due_date\":\"YYYY-MM-DD\",\"tasks\":[{\"title\":\"할일(20자)\","
    "\"due_date\":\"YYYY-MM-DD\",\"priority\":\"high|medium|low\",\"tags\":[]}]}],\"calendar_events\":[],"
    "\"summary_text\":\"2~3문장\"}\n"
    "품질: 마감 역산·하루 2~4 task·정확한 정보처리기사 과목명 사용·과락 기준 반영"
)


@dataclass(frozen=True)
class Case:
    case_id: str
    source_url: str
    time_left_days: int
    daily_hours: float | None
    start_level: str
    goal: str
    result: str
    reported_score: str
    weak_subjects: tuple[str, ...]
    process_summary: str
    review_summary: str


CASES: tuple[Case, ...] = (
    Case(
        "ipe-crawl-ozzzih-3d-pass",
        "https://ozzzih.tistory.com/44",
        3,
        5.0,
        "컴퓨터 관련 학과, 계획에 없던 빈자리 접수",
        "필기 단기 합격",
        "합격",
        "평균 70점대, 5과목 90점",
        ("정보시스템구축관리",),
        "개념서는 보지 않고 CBT 기출 모의고사 3회분을 해설까지 정독했다. 빈출 개념만 짧게 외우고 시험 직전 요약 영상과 필기 노트로 마무리했다.",
        "3일 벼락치기 후기는 평균 60점과 과목별 40점 과락 기준을 의식하며 어려운 개념보다 빈출 기출을 우선했다.",
    ),
    Case(
        "ipe-crawl-vanslife-7d-pass",
        "https://vanslife.tistory.com/81",
        7,
        3.0,
        "직장인, 비전공 출신 개발자, 1과목·3과목 기초 있음",
        "필기 합격",
        "합격",
        "1과목 60, 2과목 40, 3과목 70, 4과목 75, 5과목 80, 평균 65점",
        ("소프트웨어개발", "프로그래밍언어활용", "정보시스템구축관리"),
        "총 23~24시간 동안 일부 개념 강의와 기출 1~10회차를 병행했다. 시험 전날에는 과락이 반복되던 4·5과목을 집중 풀이하고 이동 중 오답을 반복했다.",
        "직장 병행 단기 합격 사례로, 모든 과목을 고르게 보기보다 과락 위험 과목을 마지막에 압축 보완했다.",
    ),
    Case(
        "ipe-crawl-gotopm-5d-pass",
        "https://gotopm.tistory.com/44",
        5,
        4.0,
        "비전공, 개발 부트캠프 경험 있음",
        "필기 합격",
        "합격",
        "평균 85점",
        ("데이터베이스구축", "프로그래밍언어활용"),
        "1일차에는 160쪽 분량 개념 자료를 훑고, 2~3일차에는 CBT 기출 8회분을 답·해설까지 분석했다. 4~5일차에는 2023~2024년 기출을 풀고 오답을 확인했다.",
        "5일 합격 후기는 개념 완성보다 문제은행식 기출에 익숙해지는 전략이 핵심이었다.",
    ),
    Case(
        "ipe-crawl-lshfood2-18d-pass",
        "https://lshfood2.tistory.com/258",
        18,
        2.0,
        "필기 개념서 완독은 어려운 상태",
        "필기 안정 합격",
        "합격",
        "71점",
        ("소프트웨어설계", "데이터베이스구축"),
        "약 2.5주 동안 개념서 정리 대신 CBT와 기출 풀이에 집중했고 약 800문제를 반복했다. 시험 전에는 핵심 요약 강의로 낯선 개념을 보완했다.",
        "2주 이상 준비했지만 최근 경향의 낯선 문제를 체감해, 기출 반복과 요약 개념 보완을 함께 권하는 후기다.",
    ),
    Case(
        "ipe-crawl-joosblog-5d-pass",
        "https://joosblog.tistory.com/4",
        5,
        5.0,
        "비전공, 단기 집중 가능",
        "필기 합격",
        "합격",
        "합격",
        ("데이터베이스구축", "프로그래밍언어활용", "정보시스템구축관리"),
        "5일 동안 필기 기출과 CBT를 중심으로 반복하고, 과목별 빈출 개념을 짧게 정리했다. 긴 이론 학습보다 문제 풀이와 오답 확인을 우선했다.",
        "비전공 5일 합격 사례로, 과목별 전체 범위보다 기출 반복과 오답 정리가 효과적이었다.",
    ),
    Case(
        "ipe-crawl-sofee-7d-pass",
        "https://sofee.tistory.com/61",
        7,
        3.5,
        "단기 준비, 실공부 약 24시간",
        "필기 합격",
        "합격",
        "가채점 합격",
        ("프로그래밍언어활용", "정보시스템구축관리"),
        "일주일 동안 약 24시간을 투자해 CBT 기출과 오답을 반복했다. 과락 위험 과목은 마지막에 따로 모아 집중 점검했다.",
        "짧은 준비 기간에서도 평균 60점과 과락 기준을 먼저 관리한 사례다.",
    ),
    Case(
        "ipe-crawl-ycds-2d-pass",
        "https://ycds.tistory.com/105",
        2,
        6.0,
        "IT 직장인, 주말 벼락치기",
        "필기 합격",
        "합격",
        "66점",
        ("정보시스템구축관리",),
        "주말에 CBT 기출을 2회독하고, 이후 시나공 최신 기출을 여러 번 정독했다. 모르는 문제가 많아도 반복 노출로 익숙한 문제를 확보했다.",
        "초단기 주말 합격 사례로, 이미 IT 배경이 있는 수험자가 기출 반복으로 커트라인을 넘긴 패턴이다.",
    ),
    Case(
        "ipe-crawl-kyeong8139-21d-pass",
        "https://kyeong8139.tistory.com/61",
        21,
        2.0,
        "프로젝트 병행, 필기와 실기 연계까지 고려",
        "필기 고득점 합격",
        "합격",
        "84점",
        ("정보시스템구축관리",),
        "3주 동안 영상으로 흐름을 잡고 시나공 책과 CBT로 빈출 개념을 확인했다. 마지막 주에는 CBT를 돌리며 특히 5과목을 따로 모아 풀었다.",
        "3주 준비 사례로, 실기까지 고려해 요약본을 보완하면서도 마지막은 CBT와 약점 과목 집중으로 마무리했다.",
    ),
    Case(
        "ipe-crawl-udangtang-21d-pass",
        "https://udangtang-dev.tistory.com/21",
        21,
        2.5,
        "소프트웨어공학 전공자, 다른 시험과 병행",
        "필기 합격",
        "합격",
        "합격",
        ("소프트웨어설계", "소프트웨어개발", "데이터베이스구축", "정보시스템구축관리"),
        "3주 동안 1주차에는 1~3과목, 2주차에는 4~5과목을 나누어 공부했다. 마지막 주에는 기출 풀이와 오답노트, A/B 등급 핵심 암기를 반복했다.",
        "전공자도 병행 일정에서는 과목을 주차별로 나누고 마지막 주 기출·오답으로 압축하는 방식이 유효했다.",
    ),
    Case(
        "ipe-crawl-isliife2-37d-pass",
        "https://isliife2.tistory.com/42",
        37,
        4.0,
        "전공자, 필기 9일과 실기 28일을 이어서 준비",
        "필기와 실기 1트 합격",
        "합격",
        "필기 4과목 70점 포함, 필기·실기 합격",
        ("프로그래밍언어활용", "SQL 응용"),
        "필기는 요약 영상과 요약노트 5회독 후 CBT 2020~2022년 기출을 풀고 오답을 바로 적었다. 실기는 수제비 교재로 SQL, 프로그래밍, 빈출 개념을 장기간 반복했다.",
        "필기와 실기를 함께 준비한 사례로, 필기는 9일 안에 끝내고 실기는 4주 동안 SQL·프로그래밍 중심으로 반복했다.",
    ),
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _read_crawl_rows(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("error"):
                continue
            if str(row.get("robots_allowed")) != "True":
                continue
            if int(row.get("status_code") or 0) != 200:
                continue
            rows[row["source_url"]] = row
    return rows


def _iso(today: date, days: int) -> str:
    return (today + timedelta(days=days)).isoformat()


def _task(title: str, due: str, priority: str, tags: list[str]) -> dict[str, Any]:
    return {"title": title, "due_date": due, "priority": priority, "tags": tags}


def _phase_due(today: date, total_days: int, offset: int) -> str:
    return _iso(today, min(max(offset, 0), max(total_days - 1, 0)))


def _build_plan(case: Case, info: dict[str, Any], today: date) -> dict[str, Any]:
    subjects = info["exam_parts"]["written"]["subjects"]
    deadline = _iso(today, case.time_left_days)
    weak_subjects = list(case.weak_subjects)
    first_weak = weak_subjects[0] if weak_subjects else "약점 과목"
    second_weak = weak_subjects[1] if len(weak_subjects) > 1 else "기출 오답"
    title_days = f"{case.time_left_days}일" if case.time_left_days < 30 else "5주"

    if case.time_left_days <= 5:
        phases = [
            {
                "phase": "합격 기준·범위 압축",
                "due_date": _phase_due(today, case.time_left_days, 0),
                "tasks": [
                    _task("5개 필기 과목 확인", _iso(today, 0), "high", ["정처기", "필기"]),
                    _task("과락 기준 40점 체크", _iso(today, 0), "high", ["정처기", "합격기준"]),
                ],
            },
            {
                "phase": "기출 집중 회독",
                "due_date": _phase_due(today, case.time_left_days, 2),
                "tasks": [
                    _task("CBT 기출 1회 풀기", _phase_due(today, case.time_left_days, 1), "high", ["정처기", "기출"]),
                    _task(f"{first_weak} 오답 정리", _phase_due(today, case.time_left_days, 2), "high", ["정처기", "오답"]),
                    _task(f"{second_weak} 반복 풀이", _phase_due(today, case.time_left_days, 3), "high", ["정처기", "약점"]),
                ],
            },
            {
                "phase": "시험 직전 점검",
                "due_date": _phase_due(today, case.time_left_days, case.time_left_days - 1),
                "tasks": [
                    _task("빈출 개념만 최종 암기", _phase_due(today, case.time_left_days, case.time_left_days - 1), "high", ["정처기", "암기"]),
                    _task("과목별 40점 미만 점검", _phase_due(today, case.time_left_days, case.time_left_days - 1), "high", ["정처기", "과락"]),
                ],
            },
        ]
    elif case.time_left_days <= 14:
        phases = [
            {
                "phase": "1주차 개념·기출",
                "due_date": _phase_due(today, case.time_left_days, 6),
                "tasks": [
                    _task("소프트웨어설계 훑기", _iso(today, 1), "medium", ["정처기", "1과목"]),
                    _task("소프트웨어개발 기출", _iso(today, 2), "medium", ["정처기", "2과목"]),
                    _task("데이터베이스구축 오답", _iso(today, 3), "high", ["정처기", "3과목"]),
                ],
            },
            {
                "phase": "2주차 약점 보완",
                "due_date": _phase_due(today, case.time_left_days, case.time_left_days - 1),
                "tasks": [
                    _task("프로그래밍언어활용 풀이", _phase_due(today, case.time_left_days, 7), "high", ["정처기", "4과목"]),
                    _task("정보시스템구축관리 암기", _phase_due(today, case.time_left_days, 8), "high", ["정처기", "5과목"]),
                    _task("CBT 모의고사 2회", _phase_due(today, case.time_left_days, case.time_left_days - 2), "high", ["정처기", "모의고사"]),
                ],
            },
            {
                "phase": "D-1 최종 정리",
                "due_date": _phase_due(today, case.time_left_days, case.time_left_days - 1),
                "tasks": [
                    _task("과락 위험 과목 재점검", _phase_due(today, case.time_left_days, case.time_left_days - 1), "high", ["정처기", "과락"]),
                    _task("시험장·신분증 확인", _phase_due(today, case.time_left_days, case.time_left_days - 1), "medium", ["시험"]),
                ],
            },
        ]
    else:
        phases = [
            {
                "phase": "과목별 1회독",
                "due_date": _phase_due(today, case.time_left_days, 7),
                "tasks": [
                    _task("1~2과목 개념 정리", _iso(today, 2), "medium", ["정처기", "개념"]),
                    _task("3과목 DB 기출 풀이", _iso(today, 4), "high", ["정처기", "DB"]),
                    _task("4~5과목 범위 확인", _iso(today, 7), "high", ["정처기", "약점"]),
                ],
            },
            {
                "phase": "기출·오답 누적",
                "due_date": _phase_due(today, case.time_left_days, case.time_left_days - 7),
                "tasks": [
                    _task("CBT 기출 회독 시작", _phase_due(today, case.time_left_days, 10), "high", ["정처기", "기출"]),
                    _task(f"{first_weak} 보완", _phase_due(today, case.time_left_days, 12), "high", ["정처기", "약점"]),
                    _task("오답노트 반복", _phase_due(today, case.time_left_days, case.time_left_days - 7), "high", ["정처기", "오답"]),
                ],
            },
            {
                "phase": "실전 마무리",
                "due_date": _phase_due(today, case.time_left_days, case.time_left_days - 1),
                "tasks": [
                    _task("100문항 실전 풀이", _phase_due(today, case.time_left_days, case.time_left_days - 3), "high", ["정처기", "모의고사"]),
                    _task("과목별 40점 미만 점검", _phase_due(today, case.time_left_days, case.time_left_days - 1), "high", ["정처기", "합격기준"]),
                ],
            },
        ]

    daily = f"하루 {case.daily_hours:g}시간" if case.daily_hours is not None else "하루 가용시간은 미정"
    return {
        "kind": "plan",
        "title": f"정처기 필기 {title_days} 준비",
        "deadline": deadline,
        "assumptions": [],
        "phases": phases,
        "calendar_events": [{"title": "정보처리기사 필기", "due_date": deadline, "tags": ["시험", "정처기"]}],
        "summary_text": (
            f"정보처리기사 필기는 {', '.join(subjects)} 5과목이며 과목당 40점 이상, 평균 60점 이상이 합격 기준입니다. "
            f"{daily} 기준으로 {case.review_summary}"
        ),
    }


def _make_sample(case: Case, crawl_row: dict[str, Any], info: dict[str, Any], today: date) -> dict[str, Any]:
    daily = f"하루 {case.daily_hours:g}시간" if case.daily_hours is not None else "하루 가용시간 미정"
    user = (
        f"정보처리기사 필기 시험이 {case.time_left_days}일 남았어. {daily} 가능하고, "
        f"현재 상태는 {case.start_level}이야. 목표는 {case.goal}. "
        f"약한 과목은 {', '.join(case.weak_subjects) if case.weak_subjects else '아직 모르겠어'}야."
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.replace("__TODAY__", today.isoformat())},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(_build_plan(case, info, today), ensure_ascii=False)},
        ],
        "meta": {
            "id": case.case_id,
            "domain": "exam",
            "kind": "plan",
            "turn_type": "single",
            "today": today.isoformat(),
            "source": "exam-crawl-structured",
            "source_url": case.source_url,
            "source_title": crawl_row.get("title", ""),
            "exam_code": info["exam_code"],
            "exam_part": "written",
            "result": case.result,
            "reported_score": case.reported_score,
            "time_left_days": case.time_left_days,
            "daily_hours": case.daily_hours,
            "start_level": case.start_level,
            "goal": case.goal,
            "weak_subjects": list(case.weak_subjects),
            "study_process_summary": case.process_summary,
            "review_summary": case.review_summary,
            "official_sources": [source["url"] for source in info["official_sources"]],
        },
    }


def _write_csv(cases: list[Case], crawl_rows: dict[str, dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "source_url",
        "source_title",
        "exam_type",
        "time_left_days",
        "daily_hours",
        "start_level",
        "goal",
        "weak_subjects",
        "reported_score",
        "result",
        "actual_plan_summary",
        "review_summary",
        "text_length",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            crawl_row = crawl_rows[case.source_url]
            writer.writerow(
                {
                    "source_url": case.source_url,
                    "source_title": crawl_row.get("title", ""),
                    "exam_type": "정보처리기사 필기",
                    "time_left_days": case.time_left_days,
                    "daily_hours": "" if case.daily_hours is None else case.daily_hours,
                    "start_level": case.start_level,
                    "goal": case.goal,
                    "weak_subjects": ", ".join(case.weak_subjects),
                    "reported_score": case.reported_score,
                    "result": case.result,
                    "actual_plan_summary": case.process_summary,
                    "review_summary": case.review_summary,
                    "text_length": crawl_row.get("text_length", ""),
                }
            )


def _write_jsonl(samples: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 크롤 결과를 SFT 데이터셋으로 구조화")
    parser.add_argument("--crawl", type=Path, default=DEFAULT_CRAWL_PATH)
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO_PATH)
    parser.add_argument("--out-csv", type=Path, default=DEFAULT_CSV_OUT)
    parser.add_argument("--out-jsonl", type=Path, default=DEFAULT_SFT_OUT)
    parser.add_argument("--today", type=date.fromisoformat, default=date(2026, 6, 9))
    args = parser.parse_args()

    crawl_rows = _read_crawl_rows(args.crawl)
    info = _load_json(args.info)
    available_cases = [case for case in CASES if case.source_url in crawl_rows]
    if not available_cases:
        raise SystemExit("구조화 가능한 크롤 결과가 없습니다.")

    _write_csv(available_cases, crawl_rows, args.out_csv)
    samples = [_make_sample(case, crawl_rows[case.source_url], info, args.today) for case in available_cases]
    _write_jsonl(samples, args.out_jsonl)
    print(f"structured {len(samples)} cases -> {args.out_csv}, {args.out_jsonl}")


if __name__ == "__main__":
    main()
