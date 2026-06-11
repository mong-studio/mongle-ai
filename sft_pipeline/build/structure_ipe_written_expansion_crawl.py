"""정보처리기사 필기 추가 크롤 결과를 SFT messages 데이터셋으로 구조화한다."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from sft_pipeline.build.structure_ipe_crawl import (
    Case,
    _load_json,
    _make_sample,
    _read_crawl_rows,
    _write_csv,
    _write_jsonl,
)


DEFAULT_CRAWL_PATH = Path(
    "sft_pipeline/data/generated/crawl_results_information_processing_engineer_written_expansion.jsonl"
)
DEFAULT_INFO_PATH = Path("sft_pipeline/data/exam_info/information_processing_engineer.json")
DEFAULT_CSV_OUT = Path("sft_pipeline/data/generated/raw_cases_information_processing_engineer_written_expansion.csv")
DEFAULT_SFT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_written_expansion_sft.jsonl")


CASES: tuple[Case, ...] = (
    Case(
        "ipe-written-expansion-lucypothesis-9d-69",
        "https://lucypothesis.tistory.com/68",
        9,
        2.5,
        "비전공, SQLD와 CS 스터디 경험은 있지만 C·Java와 필기 5과목은 익숙하지 않음",
        "필기 합격",
        "합격",
        "69점(60/80/60/75/70)",
        ("소프트웨어설계", "소프트웨어개발", "프로그래밍언어활용", "정보시스템구축관리"),
        "9일 동안 약 23시간을 투자해 수제비 기출문제집과 CBT를 병행했다. 1·2과목은 개념 암기, 4과목은 코드 흐름 이해, 5과목은 낯선 용어 암기에 집중했다.",
        "비전공 9일 합격 사례로, 기출만 외우기보다 해설을 읽으며 이해해야 여유 있게 평균 60점을 넘길 수 있었다.",
    ),
    Case(
        "ipe-written-expansion-yun000-14d-pass",
        "https://yun000.tistory.com/110",
        14,
        2.0,
        "컴퓨터공학 전공자지만 필기 개념을 다시 정리해야 하는 상태",
        "2주 안에 필기 합격",
        "합격",
        "합격",
        ("소프트웨어설계", "소프트웨어개발"),
        "2주 동안 하루 2시간씩 유튜브 강의 정리 노트로 흐름을 잡고 기출을 풀며 오답을 정리했다. 정리 노트 1회독 후 바로 기출 합격권에 도달했다.",
        "전공자는 전 범위 완독보다 핵심 정리와 CBT 오답 반복으로 빠르게 합격권에 들어갈 수 있었다.",
    ),
    Case(
        "ipe-written-expansion-hjsong96-5d-70",
        "https://hjsong96.tistory.com/65",
        5,
        4.0,
        "교육·경영 복수전공 비전공자, 국비 교육 병행으로 공부 시간이 부족함",
        "비전공 단기 필기 합격",
        "합격",
        "평균 70점(60/75/75/75/60)",
        ("소프트웨어설계", "정보시스템구축관리"),
        "3주 전부터 시험을 훑어봤지만 실제 집중 공부는 5일 정도였다. 2020년 이후 CBT 기출 8회분을 최소 1회독하고 모르는 개념은 꼼꼼히 찾아봤다.",
        "비전공 단기 합격 사례로, 기출 출제 비중을 활용하되 과락 위험 과목은 40점 아래로 떨어지지 않게 관리했다.",
    ),
    Case(
        "ipe-written-expansion-uddt-10d-75",
        "https://uddt.tistory.com/267",
        10,
        2.0,
        "비전공자, 필기 개념서가 필요한 상태",
        "필기 합격",
        "합격",
        "평균 75점",
        ("소프트웨어설계", "소프트웨어개발", "정보시스템구축관리"),
        "10일을 잡고 1~9일차에는 매일 2시간씩 개념서를 읽고 문제를 풀었다. 마지막 하루는 온전히 기출문제를 다시 풀며 정리했다.",
        "비전공 10일 합격 사례로, 개념서를 얇게 읽은 뒤 마지막 날을 기출 복습 전용으로 비워두는 방식이 안정적이었다.",
    ),
    Case(
        "ipe-written-expansion-yseee-30d-pass",
        "https://yseee.tistory.com/entry/%EC%A0%95%EB%B3%B4%EC%B2%98%EB%A6%AC%EA%B8%B0%EC%82%AC-%EC%A0%95%EC%B2%98%EA%B8%B0-%ED%95%84%EA%B8%B0-%ED%95%A9%EA%B2%A9-%ED%9B%84%EA%B8%B0-%EA%B3%B5%EB%B6%80-%EB%B0%A9%EB%B2%95-%EB%B9%84%EC%A0%84%EA%B3%B5%EC%9E%90",
        30,
        1.5,
        "비전공이지만 관련 지식은 조금 있는 상태",
        "필기와 실기까지 이어지는 탄탄한 준비",
        "합격",
        "합격",
        ("소프트웨어설계", "소프트웨어개발", "프로그래밍언어활용"),
        "처음 준비하는 기사 시험이라 1달을 잡고 수제비 교재와 CBT 기출을 활용했다. 문제은행식 필기 특성을 이용하되 실기 준비를 위해 개념도 함께 정리했다.",
        "여유가 있는 비전공자는 필기만 넘기는 기출 회독보다 실기까지 이어질 개념 이해를 함께 쌓는 편이 낫다.",
    ),
    Case(
        "ipe-written-expansion-raon2-14d-retry-pass",
        "https://raon-2.tistory.com/87",
        14,
        2.5,
        "전공자, 하루 벼락치기 실패로 과락을 경험한 재도전자",
        "필기 재도전 합격",
        "합격",
        "2번째 응시 합격",
        ("소프트웨어설계", "소프트웨어개발", "정보시스템구축관리"),
        "첫 응시는 하루 만에 준비했다가 과락했고, 재응시 때는 2주 동안 CBT 최신 문제지를 3회독 이상 풀었다. 문제은행식 출제에 맞춰 최신 기출 반복에 집중했다.",
        "전공자도 하루 준비는 과락 위험이 크며, 재도전 때는 최소 2주 동안 최신 CBT 회독으로 안정권을 만들어야 했다.",
    ),
    Case(
        "ipe-written-expansion-holeman-37h-81",
        "https://holeman4110.github.io/certificate/engineer-information-processing-test/",
        21,
        3.0,
        "전공자, 평균 60점을 확실히 넘기는 안정 합격이 목표",
        "필기 안정 합격",
        "합격",
        "평균 81점",
        ("소프트웨어설계", "정보시스템구축관리"),
        "총 37시간을 투자해 수제비 필기 책을 2회독했다. 2020~2021년 기출은 comcbt와 책 뒤쪽 문제로 세 번씩 풀었다.",
        "전공자 안정 합격 사례로, 3주 안팎의 학습에서는 교재 2회독과 최근 기출 3회독이 고득점에 도움이 됐다.",
    ),
    Case(
        "ipe-written-expansion-34suuuuu-14d-70s",
        "https://34suuuuu.tistory.com/45",
        14,
        2.0,
        "전공자, 2024년 교재를 보유하고 있으나 최신 회차 난이도가 걱정됨",
        "필기 합격",
        "합격",
        "70점대",
        ("소프트웨어개발", "정보시스템구축관리"),
        "1주차에는 시나공 기본서에서 빈출 A등급 내용을 빠르게 훑고, 2주차에는 3개년 기출을 2회독했다. 시험 전 평균 90점대였지만 실제 시험은 낯선 문제가 많았다.",
        "전공자 2주 합격 사례로, 기출 평균이 높아도 최신 회차의 낯선 문제에 대비해 개념 빈출표를 함께 보는 편이 안전했다.",
    ),
    Case(
        "ipe-written-expansion-kanggang-2d-pass",
        "https://kanggang.tistory.com/75",
        2,
        6.0,
        "컴퓨터공학 전공자, 단 이틀만 집중 가능",
        "필기 단기 합격",
        "합격",
        "합격",
        ("소프트웨어설계", "정보시스템구축관리"),
        "첫날은 전체 과목을 훑고 둘째 날은 CBT 기출을 반복했다. 과목별 요약 노트로 암기보다 개념 흐름을 잡고 출제 패턴과 자주 나오는 지문에 익숙해졌다.",
        "전공자 2일 합격 사례로, 배경지식이 있어도 CBT 반복과 요약 노트로 과락 기준을 빠르게 점검해야 했다.",
    ),
    Case(
        "ipe-written-expansion-no-cs-2d-pass",
        "https://no-computer-science.tistory.com/18",
        2,
        2.5,
        "전공 배경이 있어 교재 비용 없이 기출 중심으로 준비하려는 상태",
        "필기 비용 최소화 합격",
        "합격",
        "합격",
        ("소프트웨어설계", "소프트웨어개발", "정보시스템구축관리"),
        "필기는 이틀 동안 하루 2~3시간씩 시나공 사이트에 올라온 2022~2024년 필기 기출만 풀었다. 별도 교재 없이 공개 기출 자료를 활용했다.",
        "비용을 줄인 단기 합격 사례로, 전공 배경이 있다면 공개 기출 회독만으로도 필기 커트라인을 넘길 수 있었다.",
    ),
    Case(
        "ipe-written-expansion-0yeonjae2-3d-pass",
        "https://0yeonjae2.tistory.com/417",
        3,
        4.0,
        "대학교 4학년 전공자, 필기와 실기를 같은 회차에 준비",
        "필기·실기 동차 합격",
        "합격",
        "필기 합격",
        ("소프트웨어설계", "소프트웨어개발", "정보시스템구축관리"),
        "필기는 3일 이하로 준비하며 시나공 기출문제집만 풀었다. 문제은행 비중이 있다고 판단해 필기에서는 기출 풀이에 집중하고, 실기에는 별도 기본서를 사용했다.",
        "전공자 동차 준비 사례로, 필기는 3일 안에 기출 중심으로 압축하고 실기 공부 시간을 더 확보하는 전략이 가능했다.",
    ),
    Case(
        "ipe-written-expansion-wune-3d-retry-80",
        "https://wune.tistory.com/21",
        3,
        5.0,
        "과거 필기 합격 후 실기 실패로 유효기간이 만료된 재도전자",
        "필기 재도전 단기 합격",
        "합격",
        "평균 80점",
        ("소프트웨어설계", "소프트웨어개발", "정보시스템구축관리"),
        "시험 3일 전부터 기출 복원 문제를 양치기했다. 개념을 깊게 이해할 시간이 부족해 문제은행의 장점을 살리고 과목별 과락을 피하는 데 집중했다.",
        "재도전 3일 합격 사례로, 이전 경험이 있어도 유효기간 만료 후에는 기출 복원 문제로 감각을 되살리는 과정이 필요했다.",
    ),
    Case(
        "ipe-written-expansion-yuuu0823-fail-retry",
        "https://yuuu0823.tistory.com/entry/%EC%A0%95%EB%B3%B4%EC%B2%98%EB%A6%AC%EA%B8%B0%EC%82%AC-%ED%95%84%EA%B8%B0-20200606-%EA%B8%B0%EC%B6%9C-%EC%98%A4%EB%8B%B5%EC%A0%95%EB%A6%AC",
        14,
        2.0,
        "필기에서 떨어졌고 CBT 재풀이에서도 과락이 나온 재도전자",
        "과락 과목 보완 후 재응시",
        "불합격",
        "CBT 재풀이 과락",
        ("프로그래밍언어활용", "정보시스템구축관리"),
        "2020년 6월 6일 필기에서 떨어진 뒤 CBT 기출 재풀이도 과락이 나왔다. 프로그래밍언어활용을 가장 약한 과목으로 판단하고 오답노트를 작성했다.",
        "불합격 재도전 사례로, 단순 기출 반복보다 프로그래밍언어활용 오답을 유형화하고 과목별 40점 미만을 먼저 해소해야 했다.",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 필기 추가 크롤 결과를 SFT 데이터셋으로 구조화")
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
        raise SystemExit("구조화 가능한 필기 추가 크롤 결과가 없습니다.")

    _write_csv(cases, crawl_rows, args.out_csv)
    _write_jsonl([_make_sample(case, crawl_rows[case.source_url], info, args.today) for case in cases], args.out_jsonl)
    print(f"structured {len(cases)} written expansion cases -> {args.out_csv}, {args.out_jsonl}")


if __name__ == "__main__":
    main()
