"""정보처리기사 불합격·재도전 중심 크롤 결과를 SFT messages 데이터셋으로 구조화한다."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from sft_pipeline.build.structure_ipe_crawl import (
    Case as WrittenCase,
    _load_json,
    _make_sample as _make_written_sample,
    _read_crawl_rows,
)
from sft_pipeline.build.structure_ipe_practical_crawl import (
    Case as PracticalCase,
    _make_sample as _make_practical_sample,
)


DEFAULT_CRAWL_PATH = Path("sft_pipeline/data/generated/crawl_results_information_processing_engineer_retry_expansion.jsonl")
DEFAULT_INFO_PATH = Path("sft_pipeline/data/exam_info/information_processing_engineer.json")
DEFAULT_CSV_OUT = Path("sft_pipeline/data/generated/raw_cases_information_processing_engineer_retry_expansion.csv")
DEFAULT_SFT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_retry_expansion_sft.jsonl")


ExamPart = Literal["written", "practical"]


@dataclass(frozen=True)
class RetryCase:
    case_id: str
    source_url: str
    exam_part: ExamPart
    time_left_days: int
    daily_hours: float | None
    start_level: str
    goal: str
    result: str
    reported_score: str
    weak_topics: tuple[str, ...]
    process_summary: str
    review_summary: str

    def to_sample(self, row: dict[str, Any], info: dict[str, Any], today: date) -> dict[str, Any]:
        if self.exam_part == "written":
            return _make_written_sample(
                WrittenCase(
                    self.case_id,
                    self.source_url,
                    self.time_left_days,
                    self.daily_hours,
                    self.start_level,
                    self.goal,
                    self.result,
                    self.reported_score,
                    self.weak_topics,
                    self.process_summary,
                    self.review_summary,
                ),
                row,
                info,
                today,
            )

        return _make_practical_sample(
            PracticalCase(
                self.case_id,
                self.source_url,
                self.time_left_days,
                self.daily_hours,
                self.start_level,
                self.goal,
                self.result,
                self.reported_score,
                self.weak_topics,
                self.process_summary,
                self.review_summary,
            ),
            row,
            info,
            today,
        )


CASES: tuple[RetryCase, ...] = (
    RetryCase(
        "ipe-retry-nicotina-written-59-fail",
        "https://nicotina04.tistory.com/327",
        "written",
        14,
        2.0,
        "비전공 직장인, 기출문제를 통암기했지만 59점으로 필기 불합격",
        "필기 재응시 합격",
        "불합격",
        "59점",
        ("데이터베이스구축", "소프트웨어설계", "정보시스템구축관리"),
        "기출문제를 통째로 외우는 전략으로 준비했지만 1점 차이로 불합격했다. 비전공자는 요약본을 속독한 뒤 기출 오답에서 모르는 개념을 보완해야 한다는 회고가 남았다.",
        "필기 59점 불합격 사례로, 단순 암기보다 약한 과목의 개념 공백을 찾아 과목별 40점 미만 위험을 먼저 줄여야 했다.",
    ),
    RetryCase(
        "ipe-retry-devzzi-written-fail-to-72",
        "https://devzzi.tistory.com/9",
        "written",
        3,
        5.0,
        "전공자, 첫 응시에서 문제 2개 차이로 필기 불합격 후 재도전",
        "필기 재도전 합격",
        "합격",
        "첫 응시 불합격, 재응시 평균 72점",
        ("소프트웨어설계", "데이터베이스구축"),
        "첫 응시는 실공부 약 6시간과 모의고사 2회분 오답 정리만으로 봤다가 2문제 차이로 불합격했다. 재도전 때는 3일 동안 시나공 A단계와 연습문제, 이전 오답노트, 추가 개념 파일을 복습해 평균 72점으로 합격했다.",
        "필기 재도전 사례로, 전공자도 오답노트를 재활용하고 빈출 등급을 압축해 다시 풀면 단기간에 합격권으로 회복할 수 있었다.",
    ),
    RetryCase(
        "ipe-retry-codingbuza-practical-59-to-75",
        "https://codingbuza.tistory.com/105",
        "practical",
        30,
        2.5,
        "실기 2회차에서 기출 위주로만 준비했다가 59점 불합격",
        "실기 재도전 합격",
        "합격",
        "2회차 59점 불합격, 3회차 75점 합격",
        ("프로그래밍언어활용", "SQL 응용", "소프트웨어 개발 보안 구축"),
        "실기도 기출만 보면 된다고 접근했다가 59점으로 불합격했다. 이후 수제비 실기 기본서를 바탕으로 공부 방법을 전면 수정해 3회차에서 75점으로 합격했다.",
        "실기 59점 재도전 사례로, 커트라인 근처에서 떨어진 경우 기출 반복에 기본서 해설과 개념 보완을 붙여야 했다.",
    ),
    RetryCase(
        "ipe-retry-new30-practical-nsu-pass",
        "https://new-30.tistory.com/18",
        "practical",
        30,
        3.0,
        "비전공, 실기 여러 번 불합격 후 필기부터 다시 재도전한 N수생",
        "실기 최종 합격",
        "합격",
        "N수 후 최종 합격",
        ("프로그래밍언어활용", "SQL 응용"),
        "시험 4주 전부터 실기를 본격적으로 준비했다. 2020~2023년 기출 13회치에서 프로그래밍과 SQL 문제를 먼저 골라 3회독 이상 풀고, 2주 전부터 나머지 이론 문제를 반복했다.",
        "비전공 N수생 합격 사례로, 방대한 기본서 순서대로 보기보다 프로그래밍과 SQL을 먼저 고정 점수원으로 만드는 전략이 효과적이었다.",
    ),
    RetryCase(
        "ipe-retry-uujjjjjnn-practical-fail",
        "https://uujjjjjnn.tistory.com/61",
        "practical",
        45,
        2.0,
        "실기 2차·3차 모두 불합격, 학원 프로젝트와 건강 문제로 실전 풀이가 부족함",
        "다음 실기 재도전",
        "불합격",
        "2023년 2차·3차 실기 불합격",
        ("프로그래밍언어활용", "SQL 응용", "응용 SW 기초 기술 활용"),
        "2차는 프로젝트 기간과 겹쳐 거의 공부하지 못했고, 3차는 한 달 동안 강의를 봤지만 직접 푸는 시간이 부족했다. 시험 후에는 계산 문제를 매일 풀고 이론을 무작정 암기하지 말아야 한다고 정리했다.",
        "실기 연속 불합격 사례로, 강의를 보는 시간보다 직접 계산·코드·SQL을 푸는 시간을 주간 루틴으로 고정해야 했다.",
    ),
    RetryCase(
        "ipe-retry-swimjiy-practical-57-to-65",
        "https://swimjiy.github.io/2019-08-16-passing-skill-test/",
        "practical",
        21,
        4.0,
        "비전공, 1차 실기에서 57점 불합격 후 2차 재도전",
        "실기 재도전 합격",
        "합격",
        "1차 57점 불합격, 2차 65점 합격",
        ("요구사항 확인", "데이터 입출력 구현", "SQL 응용"),
        "하루 4시간씩 3주 동안 시나공 교재, 퀴즐렛, 학습 기록을 활용했다. 첫 불합격 때 4·5과목에 시간을 많이 쓴 것을 반성하고, 재도전에서는 1·2·3과목과 SQL에 집중했다.",
        "실기 57점 재도전 사례로, 점수 효율이 낮은 영역에 과투자하지 않고 출제 확률이 높은 영역으로 시간을 재배치해야 했다.",
    ),
    RetryCase(
        "ipe-retry-getusedto-practical-3try",
        "https://getusedtoitaivle.tistory.com/61",
        "practical",
        21,
        3.0,
        "비전공, 필기 합격 후 실기 2회 불합격을 겪고 직장 병행 중",
        "실기 3번째 합격",
        "합격",
        "실기 3번째 응시 합격",
        ("프로그래밍언어활용", "SQL 응용", "응용 SW 기초 기술 활용"),
        "작년에는 기출만 대충 훑고 가서 20점대와 40점대에 머물렀다. 올해는 제한된 시간 안에서 시험 공략형 공부로 전환하고, C·Java·SQL 친밀도가 낮은 부분을 처음부터 다시 정리했다.",
        "비전공 3트 합격 사례로, 이전 시험에서 체감한 출제 유형을 기준으로 약한 코드와 SQL을 집중 보완한 것이 점수 상승으로 이어졌다.",
    ),
    RetryCase(
        "ipe-retry-fabulous7-practical-3w-61",
        "https://fabulous7.tistory.com/entry/%EC%A0%95%EB%B3%B4%EC%B2%98%EB%A6%AC%EA%B8%B0%EC%82%AC-%EC%8B%A4%EA%B8%B0-%ED%9B%84%EA%B8%B0%EB%B9%84%EC%A0%84%EA%B3%B5%EC%9E%90-3%EC%A3%BC-%EA%B3%B5%EB%B6%80",
        "practical",
        21,
        3.5,
        "컴퓨터와 무관한 경력의 비전공자, 동차 필기 후 실기 준비 시간이 3주뿐임",
        "실기 커트라인 합격",
        "합격",
        "61점",
        ("프로그래밍언어활용", "SQL 응용", "애플리케이션 테스트 관리"),
        "하루 3~4시간씩 3주 동안 준비했다. 코딩을 할 줄 몰라 수제비 파이널 모의고사와 수제비 카페 해설을 적극 활용하고, 자투리 시간에는 약술형 자료와 유튜브를 반복했다.",
        "비전공 61점 합격 사례로, 시간이 부족하면 코드 해설을 찾아 직접 이해하고 커트라인 점수원을 명확히 잡아야 했다.",
    ),
    RetryCase(
        "ipe-retry-dailystudy-practical-3y-pass",
        "https://dailystudy.tistory.com/190",
        "practical",
        30,
        2.0,
        "직장 병행, 실기 3년 장기 재도전 끝에 필기 유효기간 만료까지 경험",
        "실기 장기 재도전 합격",
        "합격",
        "3년 만에 실기 합격",
        ("프로그래밍언어활용", "SQL 응용", "소프트웨어 개발 보안 구축"),
        "업무와 연차 변수 때문에 공부 시간이 자주 줄었다. 마지막 회차에는 예전 기출과 최근 3년 실기 경향, 수제비 파이널 모의고사, 이론 요약집을 핵심 위주로 복습했다.",
        "직장인 장기 재도전 사례로, 시간이 부족할수록 최근 출제 경향과 틀린 문제 복습을 중심으로 버릴 것과 잡을 것을 분리해야 했다.",
    ),
    RetryCase(
        "ipe-retry-programming-bellybutton-practical-delayed-78",
        "https://programming-bellybutton.tistory.com/m/227",
        "practical",
        21,
        2.5,
        "비전공, 필기 합격 후 실기를 오래 미루다가 응시",
        "실기 합격",
        "합격",
        "78점",
        ("프로그래밍언어활용", "SQL 응용", "소프트웨어 개발 보안 구축"),
        "필기는 3일 벼락치기로 통과했지만 실기는 한참 미루다 2024년 2회차에 응시했다. 실기 난도가 높다고 판단해 교재와 무료 강의를 병행하고 최소 2주 이상 준비 기간을 확보하는 쪽을 권했다.",
        "비전공 실기 지연 응시 사례로, 필기 합격 직후 실기를 미루면 감각이 떨어지므로 코드와 SQL 중심의 재시동 기간이 필요했다.",
    ),
)


def _write_csv(cases: list[RetryCase], rows: dict[str, dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "source_url",
        "source_title",
        "exam_part",
        "time_left_days",
        "daily_hours",
        "start_level",
        "goal",
        "weak_topics",
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
            row = rows[case.source_url]
            writer.writerow(
                {
                    "source_url": case.source_url,
                    "source_title": row.get("title", ""),
                    "exam_part": case.exam_part,
                    "time_left_days": case.time_left_days,
                    "daily_hours": "" if case.daily_hours is None else case.daily_hours,
                    "start_level": case.start_level,
                    "goal": case.goal,
                    "weak_topics": ", ".join(case.weak_topics),
                    "reported_score": case.reported_score,
                    "result": case.result,
                    "actual_plan_summary": case.process_summary,
                    "review_summary": case.review_summary,
                    "text_length": row.get("text_length", ""),
                }
            )


def _write_jsonl(samples: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 재도전 중심 크롤 결과를 SFT 데이터셋으로 구조화")
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
        raise SystemExit("구조화 가능한 재도전 크롤 결과가 없습니다.")

    _write_csv(cases, crawl_rows, args.out_csv)
    _write_jsonl([case.to_sample(crawl_rows[case.source_url], info, args.today) for case in cases], args.out_jsonl)
    print(f"structured {len(cases)} retry cases -> {args.out_csv}, {args.out_jsonl}")


if __name__ == "__main__":
    main()
