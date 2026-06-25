"""urls_opic.txt 의 크롤 가능한 후기 → raw_cases_opic.csv (run_structure 입력 계약).

컬럼은 structure/fields.py RAW_COLUMNS 를 따른다(time_left/daily_hours 는 파싱 가능한
문자열). 네이버 43개는 크롤러로 본문을 못 읽어 제외(사용자 결정). 13개만 채택.
저작권 안전: 원문 인용 없이 준비기간·수준·목표·전략 요약만 구조화한다.
"""
import csv
from pathlib import Path

OUT = Path("sft_pipeline/data/generated/raw_cases_opic.csv")
FIELDS = [
    "source_url", "source_title", "exam_type", "time_left", "daily_hours",
    "start_level", "goal", "special_notes", "actual_plan_summary",
    "result", "evidence_spans",
]

CASES = [
    # --- 기존 structure_opic_crawl.py CASES 7건 (run_structure 계약으로 변환) ---
    dict(
        source_url="https://heeyaete.com/entry/%EC%98%A4%ED%94%BD-%EC%8B%9C%ED%97%98-%EB%8F%85%ED%95%99-%ED%9B%84%EA%B8%B0feat-IM2%EC%97%90%EC%84%9C-IH-%EB%90%98%EA%B8%B0%EA%B9%8C%EC%A7%80",
        source_title="오픽 시험 독학 후기 (IM2에서 IH 되기까지)",
        exam_type="OPIc", time_left="14일", daily_hours="1.5시간",
        start_level="토익 910점, 영어 말하기 초급, 이전 시험 IM2 보유",
        goal="IH", special_notes="스크립트 암기 의존",
        actual_plan_summary="여우오픽 모의고사 200문제를 한국어로 먼저 답한 뒤 영어로 번역해 스크립트를 만들고, 통암기 대신 흐름을 익혔다. um·you know 같은 필러를 의식적으로 써서 외운 티를 줄였다.",
        result="합격", evidence_spans=""),
    dict(
        source_url="https://velog.io/@feel1toa/%EC%B2%AB-%EC%98%A4%ED%94%BD-AL-%EB%8F%85%ED%95%99-%ED%95%A9%EA%B2%A9-%ED%9B%84%EA%B8%B0%EC%9D%BC%EC%A3%BC%EC%9D%BC-%EB%8B%A8%EA%B8%B0-%EB%B2%BC%EB%9D%BD%EC%B9%98%EA%B8%B0-ey132vgd",
        source_title="첫 오픽 AL 독학 합격 후기 (일주일 단기 벼락치기)",
        exam_type="OPIc", time_left="7일", daily_hours="1.5시간",
        start_level="고교 영어 상위권, 외국인 친구 있음, 해외 거주 경험 없음",
        goal="AL", special_notes="",
        actual_plan_summary="실질 4일 학습으로 1일차 시험 형식 분석·AL 유튜브, 2일차 기본 스크립트·핵심 표현, 3일차 시간제 모의시험, 4일차 최종 복습 순으로 진행했다.",
        result="합격", evidence_spans=""),
    dict(
        source_url="https://brunch.co.kr/@camilaaashj/14",
        source_title="오픽 2주 독학 후기 (AL 목표, IH 정착)",
        exam_type="OPIc", time_left="14일", daily_hours="1시간",
        start_level="일상영어 회화 가능, 해외 거주 경험 없음",
        goal="AL", special_notes="AL 수준 논리력·유창성 부족",
        actual_plan_summary="오픽노잼 유튜브와 ChatGPT 모의고사로 설문 기반 4가지 질문 유형(묘사·습관·비교·경험)을 집중 연습했다. 하루 1시간 이내로 2주 준비했다.",
        result="불합격", evidence_spans=""),
    dict(
        source_url="https://gall.dcinside.com/mgallery/board/view/?id=opic&no=19216",
        source_title="오픽 2주 독학 IH 후기 (디시 오픽갤)",
        exam_type="OPIc", time_left="14일", daily_hours="1.5시간",
        start_level="수능 영어 3등급, 4년 영어 공백",
        goal="IH", special_notes="돌발 질문 대응 약함",
        actual_plan_summary="1주차는 오픽노잼 IM·IH 시리즈를 듣고, 2주차는 D-3에 브레인스토밍·키워드 정리, 해커스 교재로 주제 전략을 세우고 여우오픽 모의고사 2회를 풀었다.",
        result="합격", evidence_spans=""),
    dict(
        source_url="https://gall.dcinside.com/mgallery/board/view/?id=opic&no=29475",
        source_title="오픽 3일 벼락치기 IH 후기 (디시 오픽갤)",
        exam_type="OPIc", time_left="3일", daily_hours="3시간",
        start_level="토익 600점대, 토익스피킹 IL, 영어 기초 있음",
        goal="IH", special_notes="스크립트 의존",
        actual_plan_summary="오픽노잼 IM 시리즈와 여우오픽 5-6단계 모의고사 중심으로 스크립트 대신 스토리 아웃라인을 준비하고, 파파고로 낯선 단어를 찾고 필러(um, actually, honestly)를 연습했다.",
        result="합격", evidence_spans=""),
    dict(
        source_url="https://velog.io/@naninaniyoyoyoyo/%EC%9E%90%EA%B2%A9%EC%A6%9D-OPic-AL-%EC%98%A4%ED%94%BD-%EA%B3%B5%EB%B6%80%EB%B2%95-%EB%92%A4%EB%8A%A6%EC%9D%80-%EC%98%A4%ED%94%BD-%ED%9B%84%EA%B8%B0",
        source_title="OPic AL 오픽 공부법 후기",
        exam_type="OPIc", time_left="10일", daily_hours="1시간",
        start_level="영어를 일상적으로 사용하지 않음",
        goal="AL", special_notes="",
        actual_plan_summary="오픽노잼 AL 시리즈를 학습하고 유튜브 기출을 하루 한 문제씩 풀었다. 전체 스크립트 대신 핵심 단어·스토리 프레임만 준비해 멈추지 않고 계속 말하는 연습을 했다.",
        result="합격", evidence_spans=""),
    dict(
        source_url="https://velog.io/@thdekdms03/Opic-%EB%85%B8%EB%B2%A0-5%EC%9D%BC-%EA%B3%B5%EB%B6%80-IM2-%EB%8B%AC%EC%84%B1-%ED%9B%84%EA%B8%B0",
        source_title="Opic 노베 5일 공부 IM2 달성 후기",
        exam_type="OPIc", time_left="5일", daily_hours="3시간",
        start_level="노베이스, 수능 영어 2-3등급, 영어 말하기 경험 거의 없음",
        goal="IM2", special_notes="영어 말하기 경험 부족",
        actual_plan_summary="1일차 배경 설문 선택과 스크립트 작성, 2-3일차 스크립트 암기, 4일차 돌발 질문 정리·연습, 5일차 스크립트와 돌발 질문 종합 연습 순으로 진행했다.",
        result="합격", evidence_spans=""),
    # --- 신규 크롤 6건 ---
    dict(
        source_url="https://community.linkareer.com/employment_data/4136986",
        source_title="[오픽 공부법] 7일 안에 IH 고득점 비법 및 서베이 선택 팁",
        exam_type="OPIc", time_left="7일", daily_hours="",
        start_level="영어 스피킹 초중급(고득점 목표 일반 수험생)",
        goal="IH", special_notes="설문은 실제 경험 기반으로 선택, 암기 티 주의",
        actual_plan_summary="오픽노잼 IM 시리즈로 답변 구성·대처법을 익힌 뒤 여우 모의고사 5회를 풀고, 빈출 토픽 3~5개에 핵심 문장 10개를 반복 암기하며 하루 2회 이상 녹음 스피킹으로 연습했다.",
        result="", evidence_spans=""),
    dict(
        source_url="https://hereistheshell.tistory.com/88",
        source_title="오픽 첫 시험 AL 독학 후기",
        exam_type="OPIc", time_left="3일", daily_hours="",
        start_level="LA 어학연수 1년, 의사소통 가능하나 복잡한 설명 시 pause 많음, 발음 자신",
        goal="AL", special_notes="pause 많고 발화량 적음",
        actual_plan_summary="시험 일주일 전부터 미드로 영어 감을 살리고, 2일 전부터 예상 질문에 아이패드로 녹화하며 실전처럼 답변 연습을 했다. 스크립트 암기 대신 면접 준비하듯 할 말을 정리하고 원어민 유튜브로 표현을 익혔다.",
        result="합격", evidence_spans=""),
    dict(
        source_url="https://haem-jsp.tistory.com/4",
        source_title="OPIC 공부 방법 및 IH 취득 후기",
        exam_type="OPIc", time_left="3주", daily_hours="4시간",
        start_level="비전공, 문법·어휘 약함, 발음 좋고 의사소통 가능",
        goal="IM", special_notes="돌발·롤플레잉 약함, 4-4 난이도 선택",
        actual_plan_summary="오픽노잼 IM 시리즈와 1:1 가이드를 필기하며 2주 수강한 뒤, 시험 5일 전 Description·Habit·Comparison·Past Experience 유형별로 브레인스토밍해 쉬운 단어 위주 스크립트를 작성하고 녹음으로 의사전달 명확성을 점검하며 연습했다.",
        result="합격", evidence_spans=""),
    dict(
        source_url="https://jemian.tistory.com/184",
        source_title="오픽 스크립트 없이 영어회화 100일의 기적으로만 시험 후기",
        exam_type="OPIc", time_left="1일", daily_hours="1시간",
        start_level="2년 전 AL 경험, 주간 영어 스터디 참여, '영어회화 100일의 기적' 학습 중",
        goal="IH", special_notes="스크립트 없이 실력 측정 목적",
        actual_plan_summary="스크립트를 따로 쓰지 않고 영백기에서 외운 표현과 영어 스터디 말투로 실전처럼 답했다. 시험 당일 아침 영백기 MP3로 1시간 쉐도잉해 입을 풀고, 돈·핸드폰·돌발(호텔) 주제는 외운 표현을 변형해 대응했다.",
        result="합격", evidence_spans=""),
    dict(
        source_url="https://yseee.tistory.com/entry/OPIC-%EC%98%A4%ED%94%BD-%EA%B3%B5%EB%B6%80%EB%B2%95-%EB%8F%85%ED%95%99%EC%9C%BC%EB%A1%9C-12%EC%A3%BC%EB%A7%8C%EC%97%90-IH-%EB%B0%9B%EA%B8%B0-%EB%B2%BC%EB%9D%BD%EC%B9%98%EA%B8%B0-%ED%8C%81",
        source_title="OPIC 오픽 공부법 - 독학 1~2주만에 IH (벼락치기 팁)",
        exam_type="OPIc", time_left="일주일", daily_hours="",
        start_level="영어 스피킹 초중급, 첫 시도는 모의고사서 말문 막혀 취소 후 재도전",
        goal="IH", special_notes="여우오픽 모의고사 1번부터 막힘",
        actual_plan_summary="오픽노잼 IM·IH 시리즈로 시험 구조와 메인 포인트·필러 감을 잡은 뒤, 난이도 5 고정·전략적 서베이로 출제 범위를 좁히고 ChatGPT로 쉬운 단어 5문장 스크립트를 작성했다. 캠핑·공원·걷기를 한강으로, 여행 주제는 장소만 바꿔 재활용하며 핵심 질문만 준비했다.",
        result="합격", evidence_spans=""),
    dict(
        source_url="https://mansour.tistory.com/entry/opic-study-il",
        source_title="오픽 IL, IM1 공부방법 [최소 5일, 최대 2주 코스]",
        exam_type="OPIc", time_left="5일", daily_hours="3시간",
        start_level="영어 경험 거의 없음, 첫 시험 NH",
        goal="IM1", special_notes="암기 의존, 노베이스",
        actual_plan_summary="하루 안에 등급 정보·문제 유형·설문/난이도(3-3) 선택·기출·스크립트 파일 확보를 끝내고, 이후 받은 스크립트를 내 이야기로 일부 수정해 암기하며 녹음·쉐도잉으로 억양과 자신감을 반복 훈련했다.",
        result="합격", evidence_spans=""),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(CASES)
    print(f"wrote {len(CASES)} cases -> {OUT}")


if __name__ == "__main__":
    main()
