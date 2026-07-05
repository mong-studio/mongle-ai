"""teacher 증류 입력 코퍼스 — 시드 목표 × 결정론 variant, holdout 분리.

분포(스펙 §5): lifestyle 40% / routine 20% / exam 20% / project+event 20%.
Date.now()·random 금지 — 전 조합이 인덱스 산술로 결정된다.
"""
from __future__ import annotations

from datetime import date, timedelta

from sft_pipeline.experiments.planner_runtime_v2.build_dataset import (
    SCENARIOS as V2_SCENARIOS,
    Scenario,
)

# V2 README §6 비교 요청 — holdout 전용, 학습 금지 (스펙 §5)
HOLDOUT_FIXED_GOALS = (
    "흑백요리사에서 우승하고 싶어",
    "슈퍼스타K에 출연하고 싶어",
    "8월 8일 철인 삼종 경기에 출전하고 싶어",
    "이번 달에 운동이랑 공부를 챙기고 싶어",
    "아까 만든 계획에서 평일 운동을 저녁으로 바꿔줘",
)

_NEW_LIFESTYLE = tuple(
    Scenario("lifestyle", goal, success, stages)
    for goal, success, stages in [
        ("불규칙한 생활 리듬 잡기", "기상·식사·수면 시간 고정", ("현재 생활 기록", "기상 시간 고정", "식사 시간 배치", "수면 준비 루틴", "주간 리듬 점검")),
        ("퇴근 후 저녁 시간 활용", "저녁 2시간 자기시간 확보", ("저녁 시간 기록", "우선 활동 정하기", "요일별 배치", "방해 요소 정리", "주간 실천 점검")),
        ("아침형 인간 되기", "7시 기상 정착", ("현재 수면 기록", "취침 시간 앞당기기", "기상 직후 행동 정하기", "주중 실천 점검", "주말 리듬 유지")),
        ("스마트폰 사용 줄이기", "하루 사용 2시간 이하", ("현재 사용량 확인", "알림 정리", "대체 활동 배치", "취침 전 금지 시간", "주간 사용량 점검")),
        ("식비 줄이고 집밥 늘리기", "주 4회 집밥 실천", ("지출과 식사 기록", "장보기 목록 작성", "미리 준비 요일 정하기", "간단 메뉴 반복", "주간 지출 점검")),
        ("주말 무기력 벗어나기", "주말 오전 활동 정착", ("주말 패턴 기록", "오전 활동 정하기", "전날 준비 루틴", "실행 후 기록", "다음 주말 조정")),
        ("체중 감량과 수면 개선", "한 달간 두 습관 유지", ("현재 상태 기록", "식사 규칙 정하기", "가벼운 운동 배치", "수면 시간 고정", "주간 변화 점검")),
        ("공부와 아르바이트 병행", "학업 성적 유지", ("주간 시간표 확인", "공부 시간 먼저 배치", "이동 시간 활용", "피로도 점검", "다음 주 조정")),
        ("미라클 모닝 시작하기", "아침 1시간 자기계발", ("기상 목표 정하기", "아침 활동 선정", "전날 준비 루틴", "실천 기록", "주간 회고")),
        ("커피 줄이고 물 마시기", "카페인 하루 1잔", ("현재 섭취 기록", "대체 음료 준비", "시간대 규칙 정하기", "금단 증상 대비", "주간 섭취 점검")),
        ("야식 끊기", "밤 9시 이후 금식", ("야식 패턴 기록", "저녁 식사량 조정", "대체 습관 정하기", "취침 시간 앞당기기", "주간 실천 점검")),
        ("책상 앞 자세 교정", "허리 통증 줄이기", ("현재 자세 확인", "스트레칭 시간 배치", "50분 알림 설정", "의자·모니터 조정", "주간 통증 기록")),
        ("가계부 습관 만들기", "매일 지출 기록", ("기록 도구 정하기", "기록 시간 고정", "지출 분류 정리", "주간 결산", "다음 달 예산 조정")),
        ("영양제 챙겨 먹기", "하루 2회 규칙 복용", ("복용 목록 정리", "복용 시간 고정", "보관 위치 정하기", "복용 기록", "주간 점검")),
        ("반신욕과 명상 루틴", "주 3회 이완 시간", ("가능한 요일 확인", "저녁 시간 확보", "명상 방법 정하기", "실천 기록", "다음 주 조정")),
        ("이웃 소음 스트레스 관리", "수면 질 회복", ("소음 패턴 기록", "수면 환경 개선", "이완 루틴 배치", "낮 활동 조정", "주간 수면 점검")),
        ("혼자 사는 집 정리 습관", "매일 10분 정리", ("어질러진 구역 파악", "하루 구역 배정", "버릴 물건 분류", "정리 후 기록", "주간 상태 점검")),
        ("점심시간 산책 습관", "주 5회 20분 걷기", ("가능한 경로 확인", "동료와 약속 정하기", "날씨 대안 준비", "걸음 수 기록", "주간 실천 점검")),
        ("자기 전 독서 습관", "취침 전 30분 독서", ("읽을 책 정하기", "침실 환경 정리", "스마트폰 치우기", "독서 기록", "주간 진도 점검")),
        ("주중 금주 실천", "평일 음주 없이 유지", ("음주 패턴 기록", "대체 활동 정하기", "회식 대응 준비", "실천 기록", "주간 점검")),
        ("출퇴근 시간 활용", "이동 중 학습 습관", ("이동 패턴 확인", "학습 콘텐츠 선정", "구간별 활동 배치", "실천 기록", "주간 점검")),
        ("업무와 운동 균형", "주 3회 운동 지키기", ("주간 업무량 확인", "운동 요일 고정", "야근 시 대안 정하기", "피로도 기록", "다음 주 조정")),
        ("가족과 저녁 시간 확보", "주 4회 함께 식사", ("가족 일정 확인", "식사 시간 합의", "준비 역할 배분", "실천 기록", "다음 주 조정")),
        ("SNS 대신 취미 활동", "하루 1시간 취미 전환", ("사용 패턴 기록", "취미 후보 정하기", "시간대 배치", "실천 기록", "주간 회고")),
    ]
)

# 도메인별 variant 수 → 분포 40/20/20/20 (합 960)
_VARIANTS_PER_KIND = {"lifestyle": 12, "routine": 24, "exam": 16, "project": 6, "event": 6}
_LEVELS = ("처음 시작", "기초 경험 있음", "중간 수준", "한동안 쉬었음", "기본기는 익숙함")
_CAPACITIES = ("평일 1시간", "주 3회 90분", "주말 포함 하루 2시간", "주 4회", "매일 40분")
_MINUTES = (40, 60, 90, 120, 75)
_HORIZONS = (7, 12, 18, 25, 29)
_BASE = date(2026, 7, 1)


def _all_scenarios() -> tuple[Scenario, ...]:
    return tuple(V2_SCENARIOS) + _NEW_LIFESTYLE


def _make_input(scenario: Scenario, s_idx: int, variant: int) -> dict:
    today = _BASE + timedelta(days=(s_idx * 7 + variant * 13) % 150)
    horizon = _HORIZONS[variant % len(_HORIZONS)]
    deadline = today + timedelta(days=horizon)
    v5 = variant % 5
    parsed_goal = {
        "intent": "plan",
        "plan_kind": scenario.kind,
        "slots": {
            "goal": scenario.goal,
            "success_criteria": scenario.success,
            "current_state": _LEVELS[v5],
            "available_time": _CAPACITIES[v5],
        },
        "goal_text": scenario.goal,
        "goal_tag": scenario.goal.replace(" ", "")[:6],
        "deadline": deadline.isoformat(),
        "daily_capacity_minutes": _MINUTES[v5],
        "personalization_patch": {
            "preferences": ["짧고 구체적인 할 일"],
            "constraints": [_CAPACITIES[v5]],
        },
        "assumptions": [],
    }
    return {
        "input_id": f"{scenario.kind}-{s_idx:03d}-v{variant:02d}",
        "parsed_goal": parsed_goal,
        "today": today.isoformat(),
        "domain": scenario.kind,
    }


def _fixed_holdout_inputs() -> list[dict]:
    inputs = []
    for idx, goal_text in enumerate(HOLDOUT_FIXED_GOALS):
        scenario = Scenario("project", goal_text, "목표 달성", ("준비", "실행", "점검"))
        item = _make_input(scenario, 900 + idx, 0)
        item["input_id"] = f"holdout-fixed-{idx:02d}"
        item["domain"] = "project"
        inputs.append(item)
    return inputs


def build_inputs() -> tuple[list[dict], list[dict]]:
    """(train_inputs, holdout_inputs). holdout 30 = 고정 5 + 분포 미러 25."""
    everything: list[dict] = []
    for s_idx, scenario in enumerate(_all_scenarios()):
        for variant in range(_VARIANTS_PER_KIND[scenario.kind]):
            everything.append(_make_input(scenario, s_idx, variant))
    assert len(everything) == 960, len(everything)

    # 분포 미러 holdout 25건: lifestyle 10 / routine 5 / exam 5 / project 3 / event 2
    quota = {"lifestyle": 10, "routine": 5, "exam": 5, "project": 3, "event": 2}
    holdout: list[dict] = []
    train: list[dict] = []
    taken = dict.fromkeys(quota, 0)
    for i, item in enumerate(everything):
        dom = item["domain"]
        # 시나리오·variant 산포를 위해 37 간격으로 추출
        if taken[dom] < quota[dom] and i % 37 == 0:
            holdout.append(item)
            taken[dom] += 1
        else:
            train.append(item)
    # 간격 추출로 quota 미달 시 뒤에서 채움
    for dom, need in quota.items():
        while taken[dom] < need:
            idx = next(j for j in range(len(train) - 1, -1, -1) if train[j]["domain"] == dom)
            holdout.append(train.pop(idx))
            taken[dom] += 1
    holdout.extend(_fixed_holdout_inputs())
    assert len(holdout) == 30, len(holdout)
    return train, holdout
