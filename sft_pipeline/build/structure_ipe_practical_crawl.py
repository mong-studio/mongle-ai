"""정보처리기사 실기 크롤 결과를 SFT messages 데이터셋으로 구조화한다."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


DEFAULT_CRAWL_PATH = Path("sft_pipeline/data/generated/crawl_results_information_processing_engineer_practical.jsonl")
DEFAULT_INFO_PATH = Path("sft_pipeline/data/exam_info/information_processing_engineer.json")
DEFAULT_CSV_OUT = Path("sft_pipeline/data/generated/raw_cases_information_processing_engineer_practical.csv")
DEFAULT_SFT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_practical_sft.jsonl")


SYSTEM_PROMPT = (
    "너는 사용자의 일정·계획 요청을 구체적이고 실행 가능한 플랜으로 변환하는 AI 플래너다. "
    "기준일은 __TODAY__이다. 출력은 반드시 JSON만 사용한다.\n"
    "필수 수집: 시험(유형·시험일·진도·가용시간·목표)\n"
    "plan: {\"kind\":\"plan\",\"title\":\"제목(30자)\",\"deadline\":\"YYYY-MM-DD\",\"assumptions\":[],"
    "\"phases\":[{\"phase\":\"단계명\",\"due_date\":\"YYYY-MM-DD\",\"tasks\":[{\"title\":\"할일(20자)\","
    "\"due_date\":\"YYYY-MM-DD\",\"priority\":\"high|medium|low\",\"tags\":[]}]}],\"calendar_events\":[],"
    "\"summary_text\":\"2~3문장\"}\n"
    "품질: 마감 역산·하루 2~4 task·정보처리실무 범위·실기 60점 기준·SQL/프로그래밍/보안 균형 반영"
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
    weak_areas: tuple[str, ...]
    process_summary: str
    review_summary: str


CASES: tuple[Case, ...] = (
    Case(
        "ipe-practical-devje-60d-pass-3try",
        "https://devje.tistory.com/371",
        60,
        2.0,
        "실기 2회 응시 경험, SQLD 직후 재도전",
        "정보처리기사 실기 합격",
        "합격",
        "합격, 3번째 응시",
        ("프로그래밍언어활용", "SQL 응용", "소프트웨어 개발 보안 구축"),
        "약 2개월 동안 시나공 실기 기본서와 수제비 파이널 모의고사를 병행했다. 기출문제와 모의고사 해설을 중심으로 이론을 정리하고, 코딩 문제는 손코딩으로 반복했다.",
        "재도전 합격 사례로, 기본서보다 기출·모의고사 해설과 손코딩 반복이 실기 점수 확보에 더 직접적이었다.",
    ),
    Case(
        "ipe-practical-frombasics-21d-pass-after-fail",
        "https://frombasics.tistory.com/299",
        21,
        3.0,
        "비전공, 개발 1년차, 실기 1회 탈락 경험",
        "실기 안정 합격",
        "합격",
        "85~90점 예상",
        ("소프트웨어 개발 보안 구축", "프로그래밍언어활용"),
        "3주 중 앞 2주는 수제비 개념서를 읽고, 마지막 1주는 2020~2023 기출과 예상문제를 풀며 오답노트를 만들었다. C 포인터는 영상으로 보완했다.",
        "비전공 재도전 사례로, 기출만 돌리기보다 개념서 1회독과 오답노트가 약한 보안·C언어 보완에 도움이 됐다.",
    ),
    Case(
        "ipe-practical-engine-3try-pass",
        "https://engine.tistory.com/176",
        30,
        2.5,
        "전공자지만 코딩 문제에 약하고 실기 2회 실패",
        "3번째 실기 합격",
        "합격",
        "가채점 합격권",
        ("프로그래밍언어활용", "SQL 응용"),
        "코딩 문제 때문에 이전 회차에서 막혀, 유튜브 기출 해설과 예상문제로 자바·재귀·분기문을 반복했다. 개념은 빈출 보안·DB 용어 중심으로 압축했다.",
        "3트 합격 사례로, 실기에서는 기출 암기만으로 부족하고 새로운 코드 유형을 스스로 추적하는 훈련이 필요했다.",
    ),
    Case(
        "ipe-practical-doinitright-worker-90",
        "https://doinitright.tistory.com/165",
        21,
        2.0,
        "회사 병행, 만점보다 효율 목표",
        "70~80점대 합격",
        "합격",
        "최종 90점",
        ("SQL 응용", "프로그래밍언어활용", "소프트웨어 개발 보안 구축"),
        "회사와 병행해 모든 범위를 깊게 보기보다 SQL·프로그래밍 고비중 영역을 우선했다. 암기 파트는 마인드맵으로 정리하고 시험 직전까지 반복했다.",
        "직장 병행 고득점 사례로, SQL·프로그래밍 비중을 먼저 잡고 보안·디자인패턴 등 빈출 이론을 압축하는 전략이 맞았다.",
    ),
    Case(
        "ipe-practical-koreaioi-7d-borderline",
        "https://koreaioi.tistory.com/132",
        7,
        4.0,
        "전공 배경, 자료구조·C 포인터 준비 부족",
        "실기 커트라인 합격",
        "합격",
        "가답안 60점, 최종 합격",
        ("프로그래밍언어활용", "SQL 응용", "소프트웨어 개발 보안 구축"),
        "결합도·응집도·디자인패턴·테스트·정규화·SQL은 암기하고, 프로그래밍은 2023년까지의 기출 위주로 풀었다. 자료구조형 코드 문제가 어렵게 느껴졌다.",
        "커트라인 합격 사례로, 이론 암기만으로는 부족하고 프로그래밍 자료구조·코드 추적 연습이 필요했다.",
    ),
    Case(
        "ipe-practical-suldangoo-95",
        "https://suldangoo.tistory.com/37",
        21,
        3.0,
        "전공자, 필기·실기 동차 준비",
        "실기 고득점 합격",
        "합격",
        "95점",
        ("프로그래밍언어활용", "SQL 응용"),
        "시나공 실기 기본서 한 권을 중심으로 프로그래밍 언어와 DB 파트를 집중했고, 2020년 이후 최신 기출을 두 번씩 풀었다.",
        "고득점 사례로, 프로그래밍과 DB 파트를 확실히 맞추는 것이 실기 점수의 핵심이었다.",
    ),
    Case(
        "ipe-practical-codingdodo-3try-pass",
        "https://codingdodo.tistory.com/122",
        45,
        2.0,
        "실기 3번째 도전, 기출 분석 중심",
        "실기 합격",
        "합격",
        "3트 합격",
        ("프로그래밍언어활용", "SQL 응용", "응용 SW 기초 기술 활용"),
        "여러 회차를 겪으며 기출 문제를 분석하고 코딩·SQL·네트워크 계산형 문제를 따로 정리했다. 틀린 유형은 재출제 가능성을 기준으로 반복했다.",
        "다회차 도전 사례로, 실패 이력을 오답 유형으로 바꾸고 실전 문제 분석을 누적하는 방식이 효과적이었다.",
    ),
    Case(
        "ipe-practical-developtracking-30d-pass",
        "https://develop-tracking.tistory.com/125",
        30,
        3.0,
        "필기와 실기를 이어서 준비",
        "필기·실기 합격",
        "합격",
        "합격",
        ("프로그래밍언어활용", "SQL 응용", "제품소프트웨어 패키징"),
        "한 달가량 수제비 교재를 여러 번 정독하고 기출을 풀었다. C언어와 자바 코드 구조 이해에 시간을 쓰고, SQL은 기본 유형을 확실히 맞추는 쪽으로 준비했다.",
        "필기·실기 연계 사례로, 실기는 이론 다회독보다 프로그래밍 구조 이해와 SQL 기본 점수 확보가 중요했다.",
    ),
    Case(
        "ipe-practical-zo0oz-combined-pass",
        "https://zo0oz.tistory.com/98",
        28,
        2.5,
        "필기·실기 동시 합격 목표",
        "정보처리기사 합격",
        "합격",
        "합격",
        ("프로그래밍언어활용", "SQL 응용", "애플리케이션 테스트 관리"),
        "필기와 실기를 함께 준비하며 개념서, 기출, 책 추천 자료를 병행했다. 실기는 코드 문제와 SQL을 우선하고 이론은 빈출 키워드 중심으로 반복했다.",
        "동차 준비 사례로, 넓은 실기 범위를 한 번에 암기하기보다 코드·SQL·테스트 키워드를 먼저 잡았다.",
    ),
    Case(
        "ipe-practical-moneta-14d-pass",
        "https://moneta.tistory.com/1",
        14,
        3.0,
        "필기·실기 후기 기반, 단기 실기 준비",
        "실기 합격",
        "합격",
        "합격",
        ("프로그래밍언어활용", "SQL 응용", "소프트웨어 개발 보안 구축"),
        "2주 정도 필기와 실기 기출을 이어서 보고, 실기는 프로그래밍·SQL·보안 용어를 중심으로 정리했다. 시험 직전에는 자주 틀리는 코드를 다시 풀었다.",
        "단기 합격 사례로, 실기에서는 기출 회독과 코드 재풀이가 마지막 점검의 중심이었다.",
    ),
    Case(
        "ipe-practical-jigoogle-7d-68",
        "https://jigoogle.tistory.com/11",
        7,
        5.0,
        "동차 합격, 실기 1주 벼락치기",
        "실기 60점 이상",
        "합격",
        "68점",
        ("프로그래밍언어활용", "SQL 응용", "응용 SW 기초 기술 활용"),
        "시험 1주일 전 요약본으로 암기 후 기출을 돌렸고, 실전 후에는 개념서 재복습이 더 안전했겠다고 회고했다. 재귀·반복문·알고리즘과 SQL 문제를 반드시 맞추는 전략을 제시했다.",
        "벼락치기 합격 사례로, 요약본만으로는 빈틈이 생기므로 코드·SQL·네트워크 계산형 문제를 확실히 잡아야 했다.",
    ),
    Case(
        "ipe-practical-spems-7d-pass",
        "https://spems.tistory.com/116",
        7,
        4.0,
        "개발 배경 있음, 비용 최소화 독학",
        "실기 합격",
        "합격",
        "60점 이상 합격",
        ("프로그래밍언어활용", "SQL 응용", "응용 SW 기초 기술 활용"),
        "시나공 실기 책, 공개 강의, NCS·위키 자료로 이론을 정리했다. SQL은 직접 문제를 만들며 반복했고, 기출은 4일 정도 집중해서 풀이했다.",
        "독학 합격 사례로, 코드 추적은 전역 상태와 자료구조를 시각화하며 푸는 방식이 도움이 됐다.",
    ),
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _read_crawl_rows(path: Path) -> dict[str, dict[str, Any]]:
    rows = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("error") or str(row.get("robots_allowed")) != "True":
                continue
            if int(row.get("status_code") or 0) != 200:
                continue
            rows[row["source_url"]] = row
    return rows


def _iso(today: date, days: int) -> str:
    return (today + timedelta(days=days)).isoformat()


def _due(today: date, total_days: int, offset: int) -> str:
    return _iso(today, min(max(offset, 0), max(total_days - 1, 0)))


def _task(title: str, due: str, priority: str, tags: list[str]) -> dict[str, Any]:
    return {"title": title, "due_date": due, "priority": priority, "tags": tags}


def _build_plan(case: Case, info: dict[str, Any], today: date) -> dict[str, Any]:
    deadline = _iso(today, case.time_left_days)
    areas = info["exam_parts"]["practical"]["study_areas"]
    first = case.weak_areas[0]
    second = case.weak_areas[1] if len(case.weak_areas) > 1 else "SQL 응용"
    title_days = f"{case.time_left_days}일" if case.time_left_days < 30 else f"{round(case.time_left_days / 7)}주"

    if case.time_left_days <= 10:
        phases = [
            {
                "phase": "핵심 점수원 압축",
                "due_date": _due(today, case.time_left_days, 1),
                "tasks": [
                    _task("정보처리실무 범위 확인", _iso(today, 0), "high", ["정처기", "실기"]),
                    _task("실기 60점 기준 확인", _iso(today, 0), "high", ["정처기", "합격기준"]),
                    _task(f"{first} 우선 정리", _due(today, case.time_left_days, 1), "high", ["정처기", "약점"]),
                ],
            },
            {
                "phase": "기출·코드 집중",
                "due_date": _due(today, case.time_left_days, case.time_left_days - 2),
                "tasks": [
                    _task("SQL 응용 기출 풀이", _due(today, case.time_left_days, 2), "high", ["정처기", "SQL"]),
                    _task("코드 추적 손풀이", _due(today, case.time_left_days, 3), "high", ["정처기", "프로그래밍"]),
                    _task("보안·테스트 키워드 암기", _due(today, case.time_left_days, case.time_left_days - 2), "medium", ["정처기", "이론"]),
                ],
            },
            {
                "phase": "D-1 오답 마감",
                "due_date": _due(today, case.time_left_days, case.time_left_days - 1),
                "tasks": [
                    _task("틀린 코드 다시 풀기", _due(today, case.time_left_days, case.time_left_days - 1), "high", ["정처기", "오답"]),
                    _task("빈출 약어 최종 암기", _due(today, case.time_left_days, case.time_left_days - 1), "medium", ["정처기", "암기"]),
                ],
            },
        ]
    else:
        mid = max(7, case.time_left_days // 2)
        phases = [
            {
                "phase": "개념 1회독",
                "due_date": _due(today, case.time_left_days, 7),
                "tasks": [
                    _task("요구사항·데이터 입출력", _iso(today, 2), "medium", ["정처기", "이론"]),
                    _task("SQL 응용 개념 정리", _iso(today, 4), "high", ["정처기", "SQL"]),
                    _task("프로그래밍 문법 복습", _iso(today, 7), "high", ["정처기", "프로그래밍"]),
                ],
            },
            {
                "phase": "기출·오답 누적",
                "due_date": _due(today, case.time_left_days, mid),
                "tasks": [
                    _task("실기 기출 3회분 풀이", _due(today, case.time_left_days, 10), "high", ["정처기", "기출"]),
                    _task(f"{second} 오답노트", _due(today, case.time_left_days, 12), "high", ["정처기", "오답"]),
                    _task("보안·테스트 빈출 암기", _due(today, case.time_left_days, mid), "medium", ["정처기", "보안"]),
                ],
            },
            {
                "phase": "실전 마무리",
                "due_date": _due(today, case.time_left_days, case.time_left_days - 1),
                "tasks": [
                    _task("모의답안 시간 재기", _due(today, case.time_left_days, case.time_left_days - 4), "high", ["정처기", "모의"]),
                    _task("코드·SQL 최종 재풀이", _due(today, case.time_left_days, case.time_left_days - 2), "high", ["정처기", "핵심"]),
                    _task("60점 확보 과목 점검", _due(today, case.time_left_days, case.time_left_days - 1), "high", ["정처기", "합격기준"]),
                ],
            },
        ]

    daily = f"하루 {case.daily_hours:g}시간" if case.daily_hours is not None else "가용시간 미정"
    return {
        "kind": "plan",
        "title": f"정처기 실기 {title_days} 준비",
        "deadline": deadline,
        "assumptions": [],
        "phases": phases,
        "calendar_events": [{"title": "정보처리기사 실기", "due_date": deadline, "tags": ["시험", "정처기"]}],
        "summary_text": (
            f"실기는 {info['exam_parts']['practical']['subject']}이며 100점 만점 60점 이상이 합격 기준입니다. "
            f"{daily} 기준으로 {case.review_summary} 주요 범위는 {', '.join(areas[:5])} 등입니다."
        ),
    }


def _make_sample(case: Case, row: dict[str, Any], info: dict[str, Any], today: date) -> dict[str, Any]:
    daily = f"하루 {case.daily_hours:g}시간" if case.daily_hours is not None else "하루 가용시간은 아직 못 정했어"
    user = (
        f"정보처리기사 실기 시험이 {case.time_left_days}일 남았어. {daily} 가능하고, "
        f"현재 상태는 {case.start_level}이야. 목표는 {case.goal}. "
        f"약한 범위는 {', '.join(case.weak_areas)} 쪽이야."
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
            "source_title": row.get("title", ""),
            "exam_code": info["exam_code"],
            "exam_part": "practical",
            "result": case.result,
            "reported_score": case.reported_score,
            "time_left_days": case.time_left_days,
            "daily_hours": case.daily_hours,
            "start_level": case.start_level,
            "goal": case.goal,
            "weak_areas": list(case.weak_areas),
            "study_process_summary": case.process_summary,
            "review_summary": case.review_summary,
            "official_sources": [source["url"] for source in info["official_sources"]],
        },
    }


def _write_csv(cases: list[Case], rows: dict[str, dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "source_url", "source_title", "exam_type", "time_left_days", "daily_hours",
        "start_level", "goal", "weak_areas", "reported_score", "result",
        "actual_plan_summary", "review_summary", "text_length",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            row = rows[case.source_url]
            writer.writerow({
                "source_url": case.source_url,
                "source_title": row.get("title", ""),
                "exam_type": "정보처리기사 실기",
                "time_left_days": case.time_left_days,
                "daily_hours": "" if case.daily_hours is None else case.daily_hours,
                "start_level": case.start_level,
                "goal": case.goal,
                "weak_areas": ", ".join(case.weak_areas),
                "reported_score": case.reported_score,
                "result": case.result,
                "actual_plan_summary": case.process_summary,
                "review_summary": case.review_summary,
                "text_length": row.get("text_length", ""),
            })


def _write_jsonl(samples: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 실기 크롤 결과를 SFT 데이터셋으로 구조화")
    parser.add_argument("--crawl", type=Path, default=DEFAULT_CRAWL_PATH)
    parser.add_argument("--info", type=Path, default=DEFAULT_INFO_PATH)
    parser.add_argument("--out-csv", type=Path, default=DEFAULT_CSV_OUT)
    parser.add_argument("--out-jsonl", type=Path, default=DEFAULT_SFT_OUT)
    parser.add_argument("--today", type=date.fromisoformat, default=date(2026, 6, 9))
    args = parser.parse_args()

    crawl_rows = _read_crawl_rows(args.crawl)
    info = _load_json(args.info)
    cases = [case for case in CASES if case.source_url in crawl_rows]
    if not cases:
        raise SystemExit("구조화 가능한 실기 크롤 결과가 없습니다.")
    _write_csv(cases, crawl_rows, args.out_csv)
    _write_jsonl([_make_sample(case, crawl_rows[case.source_url], info, args.today) for case in cases], args.out_jsonl)
    print(f"structured {len(cases)} practical cases -> {args.out_csv}, {args.out_jsonl}")


if __name__ == "__main__":
    main()
