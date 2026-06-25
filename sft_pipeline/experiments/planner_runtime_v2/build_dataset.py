"""현재 planner 런타임 입력/출력 계약으로 300건의 결정론적 SFT 데이터를 만든다."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from adapters.todo_creation._prompts import PLAN_GENERATOR_SYSTEM, plan_generator_user
from sft_pipeline.io_utils import write_jsonl


@dataclass(frozen=True)
class Scenario:
    kind: str
    goal: str
    success: str
    stages: tuple[str, ...]


SCENARIOS = (
    # project: 낯선 고유명사와 비시험 목표를 시험 데이터로 오염시키지 않는 예시
    Scenario("project", "흑백요리사 본선 준비", "대표 요리 완성", ("대표 메뉴 후보 정리", "후보 메뉴 첫 조리", "맛 구성 피드백", "반복 조리 보완", "최종 메뉴 시연")),
    Scenario("project", "슈퍼스타K 오디션 준비", "오디션 무대 완주", ("지원 곡 후보 선정", "음역과 키 점검", "곡 해석 연습", "촬영 리허설", "오디션 영상 촬영")),
    Scenario("project", "단편영화 공모전 출품", "완성본 기한 내 제출", ("이야기 핵심 정리", "촬영 목록 작성", "주요 장면 촬영", "초벌 편집 점검", "최종 파일 제출")),
    Scenario("project", "독립 출판 원고 완성", "초고와 교정본 완성", ("목차와 분량 확정", "핵심 장면 집필", "초고 흐름 점검", "문장 교정", "원고 최종 정리")),
    Scenario("project", "개인 포트폴리오 개편", "지원 가능한 결과물 완성", ("목표 직무 정리", "대표 작업 선별", "사례 설명 작성", "전체 화면 점검", "최종본 공개")),
    Scenario("project", "작은 전시회 준비", "작품 설치와 공개", ("전시 주제 확정", "출품작 선별", "작품 설명 작성", "설치 동선 점검", "전시 공간 설치")),
    Scenario("project", "이사 준비 마무리", "이삿날 차질 없이 이동", ("보관 물건 분류", "업체 일정 확인", "필수품 따로 포장", "주소 변경 점검", "이삿날 최종 확인")),
    Scenario("project", "동아리 공연 준비", "공연 순서대로 무대 완주", ("공연 곡 순서 확정", "파트별 합주", "전체 곡 연결", "무대 동선 점검", "최종 리허설")),
    Scenario("project", "앱 출시 준비", "핵심 기능 안정화와 공개", ("출시 범위 확정", "핵심 흐름 점검", "오류 우선 수정", "배포 전 확인", "첫 버전 출시")),
    Scenario("project", "플리마켓 판매 준비", "판매 물품과 부스 준비", ("판매 품목 선정", "가격표 작성", "진열 방식 시험", "준비물 최종 점검", "부스 운영")),
    Scenario("project", "사진 공모전 출품", "주제에 맞는 작품 제출", ("공모 주제 해석", "후보 사진 선별", "색감과 구도 보정", "제출 규격 확인", "최종 작품 제출")),
    Scenario("project", "팟캐스트 첫 회 공개", "첫 에피소드 게시", ("첫 회 주제 확정", "진행 순서 작성", "시험 녹음", "음질과 흐름 편집", "첫 회 게시")),
    Scenario("project", "베란다 텃밭 만들기", "작물이 자랄 환경 구성", ("햇빛 시간 확인", "재배 작물 선정", "화분과 흙 준비", "모종 심기", "관리 상태 점검")),
    Scenario("project", "가족 여행 영상 완성", "공유 가능한 영상 제작", ("촬영본 분류", "이야기 순서 구성", "장면 초벌 편집", "자막과 소리 점검", "최종 영상 공유")),
    Scenario("project", "지역 축제 부스 준비", "행사 당일 부스 운영", ("부스 목표 정리", "운영 물품 준비", "진행 역할 배분", "현장 동선 점검", "축제 부스 운영")),
    # event
    Scenario("event", "철인 삼종 경기 완주", "수영 자전거 달리기 완주", ("현재 체력 점검", "수영 자세 훈련", "자전거 지구력 훈련", "달리기 전환 훈련", "경기 출전")),
    Scenario("event", "첫 하프마라톤 완주", "제한 시간 안에 완주", ("현재 거리 점검", "편한 속도 달리기", "긴 거리 적응", "대회 속도 점검", "하프마라톤 출전")),
    Scenario("event", "한강 자전거 대회 참가", "안전하게 코스 완주", ("자전거 상태 점검", "기본 거리 주행", "오르막 주행 연습", "보급과 장비 점검", "자전거 대회 출전")),
    Scenario("event", "오픈워터 수영 대회", "정해진 거리 완영", ("수영 거리 확인", "호흡 리듬 훈련", "연속 수영 적응", "장비와 동선 점검", "수영 대회 출전")),
    Scenario("event", "등산 대회 완주", "코스를 안전하게 완주", ("현재 보행량 점검", "계단 체력 훈련", "긴 산행 적응", "장비와 보급 점검", "등산 대회 참가")),
    Scenario("event", "동호인 테니스 대회", "경기 운영 경험 쌓기", ("기본 기술 점검", "서브 성공률 훈련", "랠리 패턴 연습", "모의 경기 진행", "테니스 대회 출전")),
    Scenario("event", "아마추어 복싱 시합", "안전하게 시합 완주", ("기초 체력 점검", "방어 동작 반복", "미트 조합 훈련", "가벼운 실전 점검", "복싱 시합 출전")),
    Scenario("event", "크로스핏 대회 참가", "종목별 동작 완수", ("동작 수준 점검", "약한 동작 보완", "복합 동작 연결", "회복과 장비 점검", "크로스핏 대회")),
    Scenario("event", "첫 트레일 러닝 대회", "산길 코스를 완주", ("현재 주행량 점검", "오르막 보행 훈련", "내리막 자세 연습", "코스와 보급 점검", "트레일 대회 출전")),
    Scenario("event", "수영 기록회 참가", "목표 거리 기록 측정", ("현재 기록 측정", "출발 동작 연습", "구간 속도 훈련", "회복과 장비 점검", "수영 기록회 참가")),
    # exam
    Scenario("exam", "정보처리기사 필기 합격", "필기시험 합격", ("출제 영역 진단", "핵심 개념 복습", "기출 문제 풀이", "오답 유형 보완", "필기시험 응시")),
    Scenario("exam", "정보처리기사 실기 합격", "실기시험 합격", ("실기 범위 진단", "핵심 용어 복습", "서술형 답안 연습", "기출 오답 보완", "실기시험 응시")),
    Scenario("exam", "토익 800점 달성", "토익 800점 이상", ("현재 점수 진단", "취약 유형 학습", "시간 제한 문제 풀이", "오답과 시간 점검", "토익 시험 응시")),
    Scenario("exam", "오픽 IM2 달성", "오픽 IM2 이상", ("현재 말하기 진단", "주제별 답변 구성", "돌발 질문 연습", "실전 녹음 점검", "오픽 시험 응시")),
    Scenario("exam", "한국사능력검정 합격", "목표 급수 합격", ("시대별 약점 진단", "핵심 흐름 복습", "기출 선지 분석", "취약 시대 보완", "한국사 시험 응시")),
    Scenario("exam", "SQLD 자격증 합격", "SQLD 시험 합격", ("과목별 수준 진단", "핵심 개념 정리", "기출 문제 풀이", "오답 개념 복습", "SQLD 시험 응시")),
    Scenario("exam", "컴퓨터활용능력 합격", "필기시험 합격", ("과목별 수준 확인", "핵심 기능 복습", "기출 문제 풀이", "시간 배분 점검", "필기시험 응시")),
    Scenario("exam", "JLPT N2 합격", "JLPT N2 합격", ("영역별 수준 진단", "어휘와 문법 복습", "독해 시간 훈련", "청해 오답 보완", "JLPT 시험 응시")),
    Scenario("exam", "공인중개사 1차 합격", "1차 시험 합격", ("과목별 약점 진단", "핵심 이론 복습", "기출 지문 분석", "실전 시간 점검", "1차 시험 응시")),
    Scenario("exam", "ADsP 자격증 합격", "ADsP 시험 합격", ("영역별 수준 진단", "핵심 용어 정리", "기출 문제 풀이", "오답 개념 보완", "ADsP 시험 응시")),
    Scenario("exam", "전산회계 1급 합격", "전산회계 시험 합격", ("이론과 실무 진단", "분개 유형 복습", "실무 문제 연습", "오답 유형 보완", "전산회계 응시")),
    Scenario("exam", "HSK 5급 합격", "HSK 5급 합격", ("영역별 수준 진단", "어휘와 문형 복습", "독해 속도 훈련", "듣기 오답 보완", "HSK 시험 응시")),
    # routine
    Scenario("routine", "아침 스트레칭 습관", "주 5회 꾸준히 실천", ("가능한 시간 정하기", "짧은 동작 시작", "동작 순서 고정", "실천 기록 확인", "다음 주 강도 조정")),
    Scenario("routine", "매일 영어 일기 쓰기", "하루 한 문단 작성", ("작성 시간 정하기", "짧은 문장 쓰기", "표현 한 개 보완", "주간 글 다시 읽기", "다음 주 주제 정리")),
    Scenario("routine", "주 3회 근력 운동", "주 3회 운동 지속", ("운동 요일 확정", "기본 동작 점검", "정해진 세트 수행", "회복 상태 기록", "다음 주 중량 조정")),
    Scenario("routine", "매일 독서하기", "하루 독서량 유지", ("읽을 책과 시간 정리", "짧은 분량 읽기", "핵심 문장 기록", "주간 진도 점검", "다음 분량 정하기")),
    Scenario("routine", "취침 시간 앞당기기", "정해진 시간에 취침", ("현재 수면 기록", "취침 알림 설정", "화면 사용 줄이기", "수면 상태 확인", "다음 주 시간 조정")),
    Scenario("routine", "주말 집 정리 습관", "주말마다 한 구역 정리", ("정리 구역 선정", "버릴 물건 분류", "물건 위치 정하기", "정리 상태 확인", "다음 구역 선정")),
    Scenario("routine", "하루 물 마시기", "목표량을 나눠 섭취", ("현재 섭취량 확인", "시간대별 양 정하기", "물병 가까이 두기", "저녁 섭취량 확인", "다음 주 목표 조정")),
    Scenario("routine", "매일 그림 연습", "하루 한 장 연습", ("연습 시간 정하기", "기본 선 연습", "관찰 그림 그리기", "그림 비교 기록", "다음 주 소재 정리")),
    # lifestyle
    Scenario("lifestyle", "운동과 자격증 공부 병행", "두 목표를 한 달간 유지", ("주간 시간표 확인", "운동 일정 고정", "공부 범위 배치", "피로와 진도 점검", "다음 주 균형 조정")),
    Scenario("lifestyle", "육아와 자기계발 균형", "무리 없는 학습 시간 확보", ("빈 시간대 확인", "짧은 학습 배치", "가족 일정과 조율", "실천 가능성 점검", "다음 주 계획 조정")),
    Scenario("lifestyle", "건강 식사와 운동 관리", "식사와 운동을 함께 유지", ("현재 생활 기록", "식사 준비일 정하기", "운동 요일 배치", "피로와 식사 점검", "다음 주 강도 조정")),
    Scenario("lifestyle", "회사 일과 이직 준비", "업무를 지키며 지원 준비", ("주간 업무량 확인", "지원 직무 정리", "포트폴리오 보완", "지원 일정 점검", "다음 주 우선순위")),
    Scenario("lifestyle", "집안일과 독서 챙기기", "집안일과 독서 모두 실천", ("이번 주 할 일 정리", "집안일 시간 배치", "독서 시간 확보", "실천량 중간 점검", "다음 주 분량 조정")),
    Scenario("lifestyle", "절약과 건강 관리", "지출과 건강 습관 개선", ("지출과 생활 기록", "주간 예산 정하기", "걷기 일정 배치", "예산과 걸음 점검", "다음 주 목표 조정")),
    Scenario("lifestyle", "학업과 동아리 병행", "과제와 활동 일정 준수", ("마감과 모임 확인", "과제 시간 먼저 배치", "동아리 준비 분배", "진도와 피로 점검", "다음 주 일정 조정")),
    Scenario("lifestyle", "반려동물 돌봄과 운동", "돌봄과 개인 운동 유지", ("돌봄 시간 확인", "산책 일정 고정", "개인 운동 배치", "피로와 실천 점검", "다음 주 강도 조정")),
    # travel/project
    Scenario("project", "제주도 가족 여행 준비", "필수 예약과 짐 준비 완료", ("가족 선호 확인", "이동과 숙소 예약", "하루 동선 정리", "공용 짐 점검", "출발 준비 완료")),
    Scenario("project", "일본 자유 여행 준비", "예약과 현지 동선 확정", ("여행 예산 정리", "항공과 숙소 확인", "지역별 동선 구성", "입장권과 교통 점검", "출발 준비 완료")),
    Scenario("project", "부산 주말 여행 준비", "짧은 일정과 예약 확정", ("가고 싶은 곳 정리", "이동편과 숙소 확인", "하루 동선 구성", "날씨별 준비 점검", "여행 짐 마무리")),
    Scenario("project", "유럽 배낭여행 준비", "장거리 여행 준비 완료", ("방문 도시 우선순위", "도시 간 이동 예약", "숙소와 예산 점검", "서류와 보험 확인", "출발 준비 완료")),
    Scenario("project", "부모님 온천 여행", "편안한 이동과 숙소 확보", ("건강과 선호 확인", "이동 부담 점검", "숙소와 식사 예약", "필요 물품 준비", "출발 전 최종 확인")),
    Scenario("project", "친구들과 캠핑 준비", "장비와 역할 준비 완료", ("참여 인원 확인", "장비 보유량 점검", "음식과 역할 배분", "날씨와 안전 확인", "캠핑 짐 마무리")),
    Scenario("project", "혼자 국내 여행 준비", "안전한 일정과 예약 완료", ("여행 목적 정리", "이동과 숙소 예약", "무리 없는 동선 구성", "비상 연락과 짐 점검", "출발 준비 완료")),
)

LEVELS = ("처음 시작", "기초 경험 있음", "중간 수준", "한동안 쉬었음", "기본기는 익숙함")
CAPACITIES = ("평일 1시간", "주 3회 90분", "주말 포함 하루 2시간", "주 4회", "매일 40분")
HORIZONS = (7, 12, 18, 29, 45)


def _spread_dates(today: date, end_offset: int, count: int) -> list[date]:
    if count == 1:
        return [today]
    offsets = [round(i * end_offset / (count - 1)) for i in range(count)]
    return [today + timedelta(days=offset) for offset in offsets]


def build_samples() -> list[dict]:
    samples: list[dict] = []
    base = date(2026, 7, 1)
    for scenario_index, scenario in enumerate(SCENARIOS):
        for variant in range(5):
            today = base + timedelta(days=(scenario_index * 3 + variant * 11) % 150)
            horizon = HORIZONS[variant]
            deadline = today + timedelta(days=horizon)
            long_horizon = horizon > 29
            detail_end = 29 if long_horizon else horizon
            stages = list(scenario.stages)
            if long_horizon:
                stages[-1] = "첫 구간 최종 점검"
            dates = _spread_dates(today, detail_end, len(stages))
            assumptions = []
            if variant == 1:
                assumptions = ["세부 요일은 일정 충돌 시 같은 주 안에서 조정"]
            elif variant == 3:
                assumptions = ["회당 실행 시간은 현재 가용 시간 안에서 조정"]

            goal = {
                "intent": "plan",
                "plan_kind": scenario.kind,
                "slots": {
                    "goal": scenario.goal,
                    "success_criteria": scenario.success,
                    "current_state": LEVELS[variant],
                    "available_time": CAPACITIES[variant],
                },
                "goal_text": scenario.goal,
                "goal_tag": scenario.goal.replace(" ", "")[:20],
                "deadline": deadline.isoformat(),
                "daily_capacity_minutes": (40, 60, 90, 120, 75)[variant],
                "personalization_patch": {
                    "preferences": ["짧고 구체적인 할 일"],
                    "constraints": [CAPACITIES[variant]],
                },
                "assumptions": assumptions,
            }
            if variant == 4 and scenario_index % 3 == 0:
                goal["previous_plan"] = {"summary_text": "초안 계획", "days": []}
                goal["revision_request"] = "주중 부담을 줄이고 주말에 핵심 연습을 배치"

            if long_horizon:
                summary = (
                    f"{scenario.goal}을 위한 첫 30일은 기초를 다지고 실행 흐름을 확인해요. "
                    f"이후에는 {scenario.success}에 맞춰 강도와 완성도를 단계적으로 높여가요."
                )
            else:
                summary = f"{scenario.goal}까지 무리하지 않고 준비와 연습, 최종 점검 순서로 진행해요."
            if assumptions:
                summary += f" 우선 '{assumptions[0]}'으로 가정해 구성했어요."

            days = [
                {
                    "date": day.isoformat(),
                    "tasks": [{"title": title, "due_date": day.isoformat()}],
                }
                for day, title in zip(dates, stages, strict=True)
            ]
            output = {
                "summary_text": summary,
                "personalization_patch": {
                    "preferences": ["짧고 구체적인 할 일"],
                    "constraints": [CAPACITIES[variant]],
                    "planning_style": ["단계별 실행"],
                },
                "days": days,
            }
            samples.append(
                {
                    "messages": [
                        {"role": "system", "content": PLAN_GENERATOR_SYSTEM},
                        {"role": "user", "content": plan_generator_user(parsed_goal=goal, today=today)},
                        {"role": "assistant", "content": json.dumps(output, ensure_ascii=False, separators=(",", ":"))},
                    ],
                    "meta": {
                        "provenance": "planner-runtime",
                        "dataset_version": "v2-300",
                        "domain": scenario.kind,
                        "kind": "plan",
                        "turn_type": "revision" if "revision_request" in goal else "single",
                        "today": today.isoformat(),
                        "scenario": scenario.goal,
                        "variant": variant,
                    },
                }
            )
    if len(samples) != 300:
        raise AssertionError(f"expected 300 samples, got {len(samples)}")
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="planner runtime v2 300건 생성")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "sft_pipeline/experiments/planner_runtime_v2/data/"
            "planner_runtime_v2_gold_300.jsonl"
        ),
    )
    args = parser.parse_args()
    samples = build_samples()
    write_jsonl(samples, args.out)
    print(f"[planner-runtime-v2] wrote {len(samples)} samples -> {args.out}")


if __name__ == "__main__":
    main()
