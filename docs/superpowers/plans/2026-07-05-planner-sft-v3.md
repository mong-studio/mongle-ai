# Planner SFT v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 플랜 생성 단일 노드용 teacher 증류 SFT 데이터셋 + 3단 정합성 게이트 + 승격 평가를 `sft_pipeline/experiments/planner_sft_v3/`에 구축한다 (스펙: `docs/superpowers/specs/2026-07-04-planner-sft-v3-design.md`).

**Architecture:** V2 실험(`planner_runtime_v2/`)의 격리 뼈대를 미러하되 데이터 생성기를 결정론 템플릿 → GPT-4o teacher 증류 + 3단 게이트 필터로 교체. 학습은 `train_plain.py`(EXAONE), 평가는 V2 `evaluate.py` 구조를 3단 루브릭으로 확장.

**Tech Stack:** Python 3.12 / pytest / openai(GPT-4o teacher·judge) / transformers+peft(`train_plain.py`) / RunPod 24GB

## Global Constraints

- `sft_pipeline/`은 루트 `.gitignore` 대상 — **모든 신규 파일은 `git add -f`** (누락 시 커밋에서 조용히 빠짐).
- 런타임 심볼 재사용 규칙: V2 선례대로 `adapters/todo_creation/_prompts.py`의 `PLAN_GENERATOR_SYSTEM`·`plan_generator_user`, `adapters/todo_creation/qwen_llm.py`의 `plan_guided_schema`·`is_korean_reply`는 **직접 import 허용**(읽기 전용). 런타임 파일 수정 금지.
- 데이터 레코드 형식은 V2와 동일: `{"messages":[{role:system|user|assistant,...}], "meta":{...}}`, assistant는 compact JSON(`ensure_ascii=False, separators=(",",":")`).
- 산출물 경로: `outputs/planner-sft-v3-*` 만 사용. 기존 HF repo·운영 `LORA_PLANNER_REPO`·V2 디렉토리 불변.
- 모든 사용자-대면 문자열은 한국어.
- 테스트 실행: `uv run pytest <path> -v` (저장소 루트에서).
- GPU/유료 단계(teacher 증류 라이브·학습·평가)는 코드 완성 후 사용자가 RunPod/API 키로 실행 — 이 계획의 테스트는 전부 오프라인(fake teacher/judge)으로 통과해야 한다.

---

### Task 1: 실험 스캐폴드 + 서빙 계약 스냅샷 sync 테스트

**Files:**
- Create: `sft_pipeline/experiments/planner_sft_v3/__init__.py` (빈 파일)
- Create: `sft_pipeline/experiments/planner_sft_v3/tests/__init__.py` (빈 파일)
- Create: `sft_pipeline/experiments/planner_sft_v3/contract.py`
- Test: `sft_pipeline/experiments/planner_sft_v3/tests/test_contract.py`

**Interfaces:**
- Produces: `contract.SYSTEM_PROMPT: str`, `contract.build_user(parsed_goal: dict, today: date) -> str`, `contract.GUIDED_SCHEMA: dict`, `contract.parse_plan_output(text: str) -> dict`(파싱 실패 시 `ValueError`). 이후 모든 태스크는 런타임 대신 이 모듈만 사용.

- [ ] **Step 1: Write the failing test**

```python
# sft_pipeline/experiments/planner_sft_v3/tests/test_contract.py
"""서빙 계약 스냅샷이 런타임 원본과 동기화돼 있는지 검사한다 (train==serve)."""
from datetime import date

import pytest

from adapters.todo_creation._prompts import PLAN_GENERATOR_SYSTEM, plan_generator_user
from adapters.todo_creation.qwen_llm import plan_guided_schema
from sft_pipeline.experiments.planner_sft_v3 import contract

GOAL = {
    "intent": "plan",
    "plan_kind": "lifestyle",
    "slots": {"goal": "운동과 독서 병행", "success_criteria": "한 달 유지"},
    "goal_text": "운동과 독서 병행",
    "goal_tag": "운동독서",
    "deadline": "2026-08-04",
    "daily_capacity_minutes": 60,
    "personalization_patch": {"preferences": [], "constraints": ["평일 1시간"]},
    "assumptions": [],
}


def test_system_prompt_matches_runtime():
    assert contract.SYSTEM_PROMPT == PLAN_GENERATOR_SYSTEM


def test_user_builder_matches_runtime():
    today = date(2026, 7, 5)
    assert contract.build_user(GOAL, today) == plan_generator_user(
        parsed_goal=GOAL, today=today
    )


def test_guided_schema_matches_runtime():
    assert contract.GUIDED_SCHEMA == plan_guided_schema()


def test_parse_plan_output_roundtrip():
    text = '{"summary_text":"요약","days":[{"date":"2026-07-06","tasks":[{"title":"스트레칭","due_date":"2026-07-06"}]}]}'
    parsed = contract.parse_plan_output(text)
    assert parsed["summary_text"] == "요약"
    assert parsed["days"][0]["tasks"][0]["title"] == "스트레칭"


def test_parse_plan_output_rejects_garbage():
    with pytest.raises(ValueError):
        contract.parse_plan_output("계획을 세워드릴게요!")
    with pytest.raises(ValueError):
        contract.parse_plan_output('{"summary_text":"요약만 있고 days 없음"}')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: sft_pipeline.experiments.planner_sft_v3`

- [ ] **Step 3: Write minimal implementation**

```python
# sft_pipeline/experiments/planner_sft_v3/contract.py
"""서빙 계약 스냅샷 — 런타임 심볼의 읽기 전용 re-export + 출력 파서.

train==serve 원칙: 데이터 생성·평가·A/B 는 전부 이 모듈만 사용한다.
런타임 계약이 바뀌면 tests/test_contract.py 의 sync 테스트가 깨져 즉시 드러난다.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from adapters.todo_creation._prompts import PLAN_GENERATOR_SYSTEM, plan_generator_user
from adapters.todo_creation.qwen_llm import plan_guided_schema

SYSTEM_PROMPT: str = PLAN_GENERATOR_SYSTEM
GUIDED_SCHEMA: dict[str, Any] = plan_guided_schema()


def build_user(parsed_goal: dict[str, Any], today: date) -> str:
    return plan_generator_user(parsed_goal=parsed_goal, today=today)


def parse_plan_output(text: str) -> dict[str, Any]:
    """모델/teacher 출력 텍스트를 계약 형태로 파싱한다. 실패 시 ValueError."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 파싱 실패: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON 객체가 아님")
    if not str(parsed.get("summary_text") or "").strip():
        raise ValueError("summary_text 누락")
    days = parsed.get("days")
    if not isinstance(days, list) or not days:
        raise ValueError("days 누락 또는 빈 배열")
    for day in days:
        if not isinstance(day, dict) or not day.get("date") or not day.get("tasks"):
            raise ValueError(f"day 형식 위반: {day!r}")
    return parsed
```

`__init__.py` 두 개는 빈 파일로 생성:

```bash
touch sft_pipeline/experiments/planner_sft_v3/__init__.py \
      sft_pipeline/experiments/planner_sft_v3/tests/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_contract.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add -f sft_pipeline/experiments/planner_sft_v3/
git commit -m "feat(sft-v3): 서빙 계약 스냅샷 + sync 테스트"
```

---

### Task 2: goal_corpus — 시드 목표·분포·holdout 분리

**Files:**
- Create: `sft_pipeline/experiments/planner_sft_v3/goal_corpus.py`
- Test: `sft_pipeline/experiments/planner_sft_v3/tests/test_goal_corpus.py`

**Interfaces:**
- Consumes: `planner_runtime_v2.build_dataset.SCENARIOS`(읽기 전용, 60종 Scenario(kind, goal, success, stages)).
- Produces: `build_inputs() -> tuple[list[dict], list[dict]]` — `(train_inputs, holdout_inputs)`. 각 input은 `{"input_id": str, "parsed_goal": dict, "today": "YYYY-MM-DD", "domain": str}`. train 935건(=960−25)·holdout 30건, 결정론(같은 호출=같은 결과).

**분포 설계(스펙 §5: 일상40/루틴20/시험20/범용20):** 시드 = V2 SCENARIOS 60종 + 신규 lifestyle 24종 = 84종. 도메인별 variant 수로 분포를 맞춘다 — lifestyle 32종×12=384(40%), routine 8종×24=192(20%), exam 12종×16=192(20%), project+event 32종×6=192(20%), 합 960. holdout 30건 = V2 README 비교 요청 5종(고정) + 도메인 미러 25건(train에서 결정론 추출·제외).

- [ ] **Step 1: Write the failing test**

```python
# sft_pipeline/experiments/planner_sft_v3/tests/test_goal_corpus.py
from collections import Counter

from sft_pipeline.experiments.planner_sft_v3.goal_corpus import (
    HOLDOUT_FIXED_GOALS,
    build_inputs,
)


def test_deterministic():
    a_train, a_hold = build_inputs()
    b_train, b_hold = build_inputs()
    assert a_train == b_train and a_hold == b_hold


def test_counts_and_distribution():
    train, hold = build_inputs()
    assert len(train) == 960 - 25  # holdout 25건은 train에서 제외
    assert len(hold) == 30
    dist = Counter(i["domain"] for i in train)
    # lifestyle 40% / routine·exam·범용(project+event) 각 20% (holdout 제외 오차 허용)
    total = sum(dist.values())
    assert abs(dist["lifestyle"] / total - 0.40) < 0.03
    assert abs(dist["routine"] / total - 0.20) < 0.03
    assert abs(dist["exam"] / total - 0.20) < 0.03
    assert abs((dist["project"] + dist["event"]) / total - 0.20) < 0.03


def test_holdout_contains_v2_readme_probes_and_no_overlap():
    train, hold = build_inputs()
    hold_goals = {h["parsed_goal"]["goal_text"] for h in hold}
    for probe in HOLDOUT_FIXED_GOALS:
        assert probe in hold_goals
    train_ids = {t["input_id"] for t in train}
    assert not train_ids & {h["input_id"] for h in hold}


def test_parsed_goal_shape():
    train, _ = build_inputs()
    goal = train[0]["parsed_goal"]
    for key in ("intent", "plan_kind", "slots", "goal_text", "goal_tag",
                "deadline", "daily_capacity_minutes", "personalization_patch"):
        assert key in goal, key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_goal_corpus.py -v`
Expected: FAIL — `ModuleNotFoundError` (goal_corpus 없음)

- [ ] **Step 3: Write the implementation**

```python
# sft_pipeline/experiments/planner_sft_v3/goal_corpus.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_goal_corpus.py -v`
Expected: 4 PASS (분포 assert 실패 시 quota/간격 상수만 조정 — 시나리오 수는 불변)

- [ ] **Step 5: Commit**

```bash
git add -f sft_pipeline/experiments/planner_sft_v3/goal_corpus.py \
           sft_pipeline/experiments/planner_sft_v3/tests/test_goal_corpus.py
git commit -m "feat(sft-v3): 목표 코퍼스 960건 + holdout 30건 분리 (분포 40/20/20/20)"
```

---

### Task 3: coherence_gate — Gate 1·2 (구문+구조 불변식, 결정론)

**Files:**
- Create: `sft_pipeline/experiments/planner_sft_v3/coherence_gate.py`
- Test: `sft_pipeline/experiments/planner_sft_v3/tests/test_coherence_gate.py`

**Interfaces:**
- Consumes: `contract.parse_plan_output`, `adapters.todo_creation.qwen_llm.is_korean_reply`.
- Produces: `check_structure(plan: dict, parsed_goal: dict, today: date) -> list[str]` — 위반 없으면 `[]`, 있으면 `["S2: ...", "S4: ..."]` 형태 사유 리스트. `EXAM_LEAK_TERMS: tuple[str, ...]`, `has_english_leak(text) -> bool`.

**불변식 구현 범위(스펙 §5 Gate 2):** S2 시간 논리(전 날짜가 today~deadline 내·days ≤30·총 task ≤15·due_date==해당 day.date), S3 부하 상한(하루 task ≤3), S4 참조 무결성(비시험 목표에 시험 어휘 금지 + summary 포함, 근거 없는 영어 금지, 한국어), S5 분량 보존(routine: "주 N회"가 slots에 있으면 첫 주 task 수 ≥ N), 중복(동일 (title, due_date) 금지).

- [ ] **Step 1: Write the failing test**

```python
# sft_pipeline/experiments/planner_sft_v3/tests/test_coherence_gate.py
from datetime import date

from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
    check_structure,
    has_english_leak,
)

TODAY = date(2026, 7, 5)


def _goal(kind="lifestyle", **over):
    goal = {
        "plan_kind": kind,
        "goal_text": "운동과 독서 병행",
        "deadline": "2026-07-20",
        "slots": {"goal": "운동과 독서 병행"},
    }
    goal.update(over)
    return goal


def _plan(days):
    return {"summary_text": "무리하지 않고 진행해요.", "days": days}


def _day(d, *titles):
    return {"date": d, "tasks": [{"title": t, "due_date": d} for t in titles]}


def test_valid_plan_passes():
    plan = _plan([_day("2026-07-06", "가벼운 운동"), _day("2026-07-10", "독서 30분")])
    assert check_structure(plan, _goal(), TODAY) == []


def test_s2_date_out_of_range():
    plan = _plan([_day("2026-09-01", "너무 늦은 일정")])
    issues = check_structure(plan, _goal(), TODAY)
    assert any(i.startswith("S2") for i in issues)


def test_s2_due_date_mismatch():
    plan = {"summary_text": "요약", "days": [
        {"date": "2026-07-06", "tasks": [{"title": "운동", "due_date": "2026-07-08"}]}]}
    assert any(i.startswith("S2") for i in check_structure(plan, _goal(), TODAY))


def test_s3_daily_overload():
    plan = _plan([_day("2026-07-06", "일1", "일2", "일3", "일4")])
    assert any(i.startswith("S3") for i in check_structure(plan, _goal(), TODAY))


def test_s4_exam_leak_in_non_exam_goal():
    plan = _plan([_day("2026-07-06", "기출 문제 풀이")])
    assert any(i.startswith("S4") for i in check_structure(plan, _goal(), TODAY))
    # 시험 목표에서는 허용
    assert check_structure(plan, _goal(kind="exam"), TODAY) == []


def test_s4_english_leak():
    plan = _plan([_day("2026-07-06", "Review the plan")])
    assert any(i.startswith("S4") for i in check_structure(plan, _goal(), TODAY))
    assert has_english_leak("Study session 준비")
    assert not has_english_leak("SQL 응용 기출풀기")  # 연속 2단어 미만 영어는 허용


def test_s5_routine_weekly_count():
    goal = _goal(kind="routine", slots={"goal": "주 3회 근력 운동", "cadence": "주 3회"})
    plan = _plan([_day("2026-07-06", "근력 운동")])  # 첫 주 1회뿐
    assert any(i.startswith("S5") for i in check_structure(plan, goal, TODAY))


def test_duplicate_task_rejected():
    plan = _plan([
        {"date": "2026-07-06", "tasks": [
            {"title": "운동", "due_date": "2026-07-06"},
            {"title": "운동", "due_date": "2026-07-06"},
        ]}
    ])
    assert any("중복" in i for i in check_structure(plan, _goal(), TODAY))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_coherence_gate.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# sft_pipeline/experiments/planner_sft_v3/coherence_gate.py
"""3단 게이트 중 Gate 2 구조 불변식(결정론) — evaluating-plan-coherence 루브릭.

위반은 침묵 교정하지 않고 사유 문자열로 반환한다(스펙 §5).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from adapters.todo_creation.qwen_llm import is_korean_reply

# 비시험 목표 플랜에 나타나면 S4 위반인 시험 어휘 (지난 실패: lifestyle→정처기 붕괴)
EXAM_LEAK_TERMS: tuple[str, ...] = (
    "기출", "모의고사", "필기시험", "실기시험", "시험 응시", "오답", "수험",
    "정보처리기사", "정처기", "토익", "오픽", "자격증",
)

_ENGLISH_RUN = re.compile(r"[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})+")  # 연속 영단어 2개 이상

_MAX_DAYS = 30
_MAX_TASKS = 15
_MAX_TASKS_PER_DAY = 3
_CADENCE = re.compile(r"주\s*(\d+)\s*회")


def has_english_leak(text: str) -> bool:
    return bool(_ENGLISH_RUN.search(text))


def _all_titles(plan: dict[str, Any]) -> list[str]:
    return [
        str(task.get("title") or "")
        for day in plan.get("days", [])
        for task in day.get("tasks", [])
    ]


def check_structure(plan: dict[str, Any], parsed_goal: dict[str, Any], today: date) -> list[str]:
    issues: list[str] = []
    days = plan.get("days", [])
    deadline = date.fromisoformat(parsed_goal["deadline"]) if parsed_goal.get("deadline") else None

    # S2 시간 논리
    if len(days) > _MAX_DAYS:
        issues.append(f"S2: days {len(days)}개 > {_MAX_DAYS}")
    titles = _all_titles(plan)
    if len(titles) > _MAX_TASKS:
        issues.append(f"S2: task {len(titles)}개 > {_MAX_TASKS}")
    for day in days:
        try:
            day_date = date.fromisoformat(str(day.get("date")))
        except ValueError:
            issues.append(f"S2: 날짜 형식 위반 {day.get('date')!r}")
            continue
        if day_date < today or (deadline and day_date > deadline):
            issues.append(f"S2: {day_date} 이 기간(today~deadline) 밖")
        for task in day.get("tasks", []):
            if str(task.get("due_date")) != str(day.get("date")):
                issues.append(f"S2: due_date {task.get('due_date')} != day {day.get('date')}")

    # S3 부하 상한
    for day in days:
        if len(day.get("tasks", [])) > _MAX_TASKS_PER_DAY:
            issues.append(f"S3: {day.get('date')} 에 task {len(day['tasks'])}개 > {_MAX_TASKS_PER_DAY}")

    # S4 참조 무결성 — summary 포함 전체 텍스트 검사 (스킬: summary 도 S4 대상)
    full_text = " ".join(titles) + " " + str(plan.get("summary_text") or "")
    if parsed_goal.get("plan_kind") != "exam":
        for term in EXAM_LEAK_TERMS:
            if term in full_text:
                issues.append(f"S4: 비시험 목표에 시험 어휘 '{term}' 혼입")
                break
    if has_english_leak(full_text):
        issues.append("S4: 근거 없는 연속 영어 혼입")
    if not is_korean_reply(full_text):
        issues.append("S4: 한국어 응답 아님")

    # S5 분량 보존 — routine 의 '주 N회' 만 결정론 검사 (그 외 도메인은 판정 불가 → 통과)
    if parsed_goal.get("plan_kind") == "routine":
        slots_text = " ".join(str(v) for v in (parsed_goal.get("slots") or {}).values())
        match = _CADENCE.search(slots_text)
        if match and days:
            weekly = int(match.group(1))
            first_day = date.fromisoformat(str(days[0]["date"]))
            week_end = first_day + timedelta(days=6)
            first_week = sum(
                len(d.get("tasks", []))
                for d in days
                if first_day <= date.fromisoformat(str(d["date"])) <= week_end
            )
            if first_week < weekly:
                issues.append(f"S5: 주 {weekly}회 요구인데 첫 주 {first_week}회 배치")

    # 중복 배치 금지
    seen: set[tuple[str, str]] = set()
    for day in days:
        for task in day.get("tasks", []):
            key = (str(task.get("title")), str(task.get("due_date")))
            if key in seen:
                issues.append(f"중복 배치: {key}")
            seen.add(key)
    return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_coherence_gate.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add -f sft_pipeline/experiments/planner_sft_v3/coherence_gate.py \
           sft_pipeline/experiments/planner_sft_v3/tests/test_coherence_gate.py
git commit -m "feat(sft-v3): Gate2 구조 불변식 검사기 (S2~S5·중복·한국어)"
```

---

### Task 4: coherence_gate — Gate 3 (의미 채점 LLM judge) + 종합 판정

**Files:**
- Modify: `sft_pipeline/experiments/planner_sft_v3/coherence_gate.py` (함수 추가)
- Test: `sft_pipeline/experiments/planner_sft_v3/tests/test_semantic_judge.py`

**Interfaces:**
- Produces: `SEMANTIC_JUDGE_SYSTEM: str`, `semantic_judge_user(plan: dict, parsed_goal: dict) -> str`, `parse_judge_reply(text: str) -> dict`(`{"M1":int,"M2":int,"M3":int,"M4":int,"average":float}`, 실패 시 `ValueError`), `verdict(parse_ok: bool, structure_issues: list[str], semantic_avg: float | None) -> str`(`"ACCEPT"|"FIX"|"DROP"`). judge LLM 호출 자체는 Task 5의 distill 러너가 수행(주입식) — 이 태스크는 프롬프트·파서·판정 규칙만.

**판정 규칙(스펙 §5):** 구문 FAIL→DROP, 구조 1개 이상 FAIL→DROP, 의미 <3.0→DROP, 3.0~3.9→FIX, ≥4.0→ACCEPT.

- [ ] **Step 1: Write the failing test**

```python
# sft_pipeline/experiments/planner_sft_v3/tests/test_semantic_judge.py
import pytest

from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
    SEMANTIC_JUDGE_SYSTEM,
    parse_judge_reply,
    semantic_judge_user,
    verdict,
)


def test_judge_prompt_mentions_all_dimensions():
    for token in ("M1", "M2", "M3", "M4", "1~5", "JSON"):
        assert token in SEMANTIC_JUDGE_SYSTEM


def test_judge_user_contains_goal_and_plan():
    text = semantic_judge_user(
        {"summary_text": "요약", "days": []},
        {"goal_text": "운동과 독서 병행", "plan_kind": "lifestyle"},
    )
    assert "운동과 독서 병행" in text and "요약" in text


def test_parse_judge_reply():
    reply = '{"M1": 4, "M2": 5, "M3": 4, "M4": 3}'
    scores = parse_judge_reply(reply)
    assert scores["average"] == 4.0


def test_parse_judge_reply_rejects_out_of_range():
    with pytest.raises(ValueError):
        parse_judge_reply('{"M1": 9, "M2": 1, "M3": 1, "M4": 1}')
    with pytest.raises(ValueError):
        parse_judge_reply("좋은 계획이네요")


def test_verdict_rules():
    assert verdict(False, [], None) == "DROP"            # 구문 FAIL
    assert verdict(True, ["S2: ..."], 5.0) == "DROP"      # 구조 FAIL 은 점수로 희석 금지
    assert verdict(True, [], 2.9) == "DROP"
    assert verdict(True, [], 3.5) == "FIX"
    assert verdict(True, [], 4.0) == "ACCEPT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_semantic_judge.py -v`
Expected: FAIL — `ImportError: SEMANTIC_JUDGE_SYSTEM`

- [ ] **Step 3: Write the implementation** (coherence_gate.py 하단에 추가)

```python
# coherence_gate.py 하단에 추가
import json

SEMANTIC_JUDGE_SYSTEM = """당신은 일정 계획의 논리성을 채점하는 심사자다.
사용자 목표와 계획(JSON)을 보고 아래 4개 차원을 각각 1~5 정수로 채점한다.

- M1 분배 합리성: "1일차, 2일차…" 식 기계적 균등 분할이 아니라 난이도와 맥락을 반영해 배분했는가
- M2 시간 현실성: 항목당 부하가 현실적이고 무리한 몰아넣기가 없는가
- M3 순서 논리: 선행→후행 의존을 지키는가 (점검은 실행 후, 기초는 심화 전)
- M4 완결성: 이 계획대로 하면 사용자 목표가 실제로 달성되는가

반드시 아래 JSON 형식으로만 답한다. 설명·서술 금지.
{"M1": <1~5>, "M2": <1~5>, "M3": <1~5>, "M4": <1~5>}"""


def semantic_judge_user(plan: dict[str, Any], parsed_goal: dict[str, Any]) -> str:
    return (
        f"[사용자 목표]\n{parsed_goal.get('goal_text')}"
        f" (유형: {parsed_goal.get('plan_kind')})\n\n"
        f"[계획]\n{json.dumps(plan, ensure_ascii=False)}"
    )


def parse_judge_reply(text: str) -> dict[str, Any]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge JSON 파싱 실패: {exc}") from exc
    scores = {}
    for key in ("M1", "M2", "M3", "M4"):
        value = raw.get(key)
        if not isinstance(value, int) or not 1 <= value <= 5:
            raise ValueError(f"{key} 점수 범위 위반: {value!r}")
        scores[key] = value
    scores["average"] = round(sum(scores.values()) / 4, 2)
    return scores


def verdict(parse_ok: bool, structure_issues: list[str], semantic_avg: float | None) -> str:
    """스펙 §5 판정 규칙. 구조 위반은 의미 점수로 희석하지 않는다."""
    if not parse_ok or structure_issues:
        return "DROP"
    if semantic_avg is None or semantic_avg < 3.0:
        return "DROP"
    if semantic_avg < 4.0:
        return "FIX"
    return "ACCEPT"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/ -v`
Expected: 전체 PASS (기존 Gate 1·2 테스트 포함 회귀 없음)

- [ ] **Step 5: Commit**

```bash
git add -f sft_pipeline/experiments/planner_sft_v3/coherence_gate.py \
           sft_pipeline/experiments/planner_sft_v3/tests/test_semantic_judge.py
git commit -m "feat(sft-v3): Gate3 의미 채점 프롬프트·파서·ACCEPT/FIX/DROP 판정"
```

---

### Task 5: distill_dataset — teacher 증류 러너 (재개 캐시 + 드롭 사유 리포트)

**Files:**
- Create: `sft_pipeline/experiments/planner_sft_v3/distill_dataset.py`
- Test: `sft_pipeline/experiments/planner_sft_v3/tests/test_distill.py`

**Interfaces:**
- Consumes: `goal_corpus.build_inputs`, `contract.*`, `coherence_gate.*`, `sft_pipeline.io_utils.write_jsonl`.
- Produces: `run_distill(inputs: list[dict], complete: Callable[[str, str], str], judge: Callable[[str, str], str], cache_dir: Path) -> dict` — `{"accepted": list[record], "report": {"total", "accepted", "fix_retried", "dropped", "drop_reasons": {사유: 건수}}}`. `complete(system, user)`/`judge(system, user)`는 주입식(테스트=fake, 라이브=OpenAI). CLI: `python -m ...distill_dataset --out data/planner_sft_v3_gold.jsonl --holdout-out data/holdout.jsonl`.
- 레코드 형식: V2와 동일 messages 3종 + `meta={"provenance": "planner-sft-v3-distill", "dataset_version": "v3", "domain", "input_id", "today", "judge_scores"}`.

- [ ] **Step 1: Write the failing test**

```python
# sft_pipeline/experiments/planner_sft_v3/tests/test_distill.py
import json

from sft_pipeline.experiments.planner_sft_v3.distill_dataset import run_distill
from sft_pipeline.experiments.planner_sft_v3.goal_corpus import build_inputs

GOOD_PLAN_TEMPLATE = json.dumps({
    "summary_text": "무리하지 않게 준비, 실행, 점검 순서로 진행해요.",
    "days": [
        {"date": "{d0}", "tasks": [{"title": "현재 상태 점검", "due_date": "{d0}"}]},
        {"date": "{d1}", "tasks": [{"title": "핵심 연습 시작", "due_date": "{d1}"}]},
    ],
}, ensure_ascii=False)


def _plan_for(sample):
    d0 = sample["today"]
    d1 = sample["parsed_goal"]["deadline"]
    return GOOD_PLAN_TEMPLATE.replace("{d0}", d0).replace("{d1}", d1)


def _fake_judge_accept(system: str, user: str) -> str:
    return '{"M1": 4, "M2": 4, "M3": 5, "M4": 4}'


def _fake_judge_fixband(system: str, user: str) -> str:
    return '{"M1": 3, "M2": 3, "M3": 4, "M4": 4}'  # 평균 3.5 → FIX


def _lifestyle_sample():
    train, _ = build_inputs()
    return next(s for s in train if s["domain"] == "lifestyle")


def test_accepts_good_sample(tmp_path):
    sample = _lifestyle_sample()
    plan = _plan_for(sample)
    result = run_distill([sample], lambda s, u: plan, _fake_judge_accept, tmp_path)
    assert result["report"]["accepted"] == 1
    record = result["accepted"][0]
    assert record["messages"][2]["content"] == plan  # assistant == teacher 원문
    assert record["meta"]["provenance"] == "planner-sft-v3-distill"


def test_fix_band_retries_once_then_drops(tmp_path):
    sample = _lifestyle_sample()
    plan = _plan_for(sample)
    calls = {"n": 0}

    def counting_complete(s, u):
        calls["n"] += 1
        return plan

    result = run_distill([sample], counting_complete, _fake_judge_fixband, tmp_path)
    assert calls["n"] == 2  # FIX → 재생성 1회
    assert result["report"]["accepted"] == 0
    assert result["report"]["dropped"] == 1


def test_structure_violation_drops_with_reason(tmp_path):
    sample = _lifestyle_sample()
    bad = json.dumps({"summary_text": "요약", "days": [
        {"date": "2030-01-01", "tasks": [{"title": "기출 문제 풀이", "due_date": "2030-01-01"}]}
    ]}, ensure_ascii=False)
    result = run_distill([sample], lambda s, u: bad, _fake_judge_accept, tmp_path)
    assert result["report"]["accepted"] == 0
    assert any("S2" in reason for reason in result["report"]["drop_reasons"])


def test_resume_cache_skips_completed(tmp_path):
    sample = _lifestyle_sample()
    plan = _plan_for(sample)
    run_distill([sample], lambda s, u: plan, _fake_judge_accept, tmp_path)

    def boom(s, u):
        raise AssertionError("캐시 히트면 teacher 재호출 금지")

    result = run_distill([sample], boom, _fake_judge_accept, tmp_path)
    assert result["report"]["accepted"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_distill.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# sft_pipeline/experiments/planner_sft_v3/distill_dataset.py
"""GPT-4o teacher 증류 러너 — 3단 게이트 필터 + input_id 단위 재개 캐시.

라이브 실행(비용 발생): OPENAI_API_KEY 필요.
  uv run python -m sft_pipeline.experiments.planner_sft_v3.distill_dataset \
    --out sft_pipeline/experiments/planner_sft_v3/data/planner_sft_v3_gold.jsonl \
    --holdout-out sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable

from sft_pipeline.experiments.planner_sft_v3 import contract
from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
    SEMANTIC_JUDGE_SYSTEM,
    check_structure,
    parse_judge_reply,
    semantic_judge_user,
    verdict,
)
from sft_pipeline.experiments.planner_sft_v3.goal_corpus import build_inputs
from sft_pipeline.io_utils import write_jsonl

CompleteFn = Callable[[str, str], str]

_FIX_SUFFIX = "\n\n[재생성 요청] 직전 계획은 분배·순서·완결성 점수가 낮았다. 목표에 더 밀착한 내용으로 다시 작성하라."


def _evaluate_candidate(text: str, item: dict) -> tuple[str, list[str], dict | None, str | None]:
    """(state, structure_issues, plan, syntax_error)"""
    try:
        plan = contract.parse_plan_output(text)
    except ValueError as exc:
        return "DROP", [], None, f"구문: {exc}"
    issues = check_structure(plan, item["parsed_goal"], date.fromisoformat(item["today"]))
    if issues:
        return "DROP", issues, plan, None
    return "PENDING_JUDGE", [], plan, None


def run_distill(
    inputs: list[dict],
    complete: CompleteFn,
    judge: CompleteFn,
    cache_dir: Path,
) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    accepted: list[dict] = []
    drop_reasons: Counter[str] = Counter()
    fix_retried = 0

    for item in inputs:
        cache_file = cache_dir / f"{item['input_id']}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("record"):
                accepted.append(cached["record"])
            else:
                drop_reasons[cached["reason"]] += 1
            continue

        user = contract.build_user(item["parsed_goal"], date.fromisoformat(item["today"]))
        record, reason = None, None
        prompt_user = user
        for attempt in range(2):  # 최초 1회 + FIX 재생성 1회
            text = complete(contract.SYSTEM_PROMPT, prompt_user)
            state, issues, plan, syntax_error = _evaluate_candidate(text, item)
            if state == "DROP":
                reason = syntax_error or issues[0]
                break
            judge_reply = judge(SEMANTIC_JUDGE_SYSTEM, semantic_judge_user(plan, item["parsed_goal"]))
            try:
                scores = parse_judge_reply(judge_reply)
            except ValueError as exc:
                reason = f"judge: {exc}"
                break
            decision = verdict(True, issues, scores["average"])
            if decision == "ACCEPT":
                record = {
                    "messages": [
                        {"role": "system", "content": contract.SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": text},
                    ],
                    "meta": {
                        "provenance": "planner-sft-v3-distill",
                        "dataset_version": "v3",
                        "domain": item["domain"],
                        "input_id": item["input_id"],
                        "today": item["today"],
                        "judge_scores": scores,
                    },
                }
                break
            if decision == "FIX" and attempt == 0:
                fix_retried += 1
                prompt_user = user + _FIX_SUFFIX
                continue
            reason = f"의미 평균 {scores['average']} ({decision})"
            break

        cache_file.write_text(
            json.dumps({"record": record, "reason": reason}, ensure_ascii=False),
            encoding="utf-8",
        )
        if record:
            accepted.append(record)
        else:
            drop_reasons[reason or "unknown"] += 1

    return {
        "accepted": accepted,
        "report": {
            "total": len(inputs),
            "accepted": len(accepted),
            "fix_retried": fix_retried,
            "dropped": sum(drop_reasons.values()),
            "drop_reasons": dict(drop_reasons),
        },
    }


def _openai_fns() -> tuple[CompleteFn, CompleteFn]:
    from openai import OpenAI  # crawl/daily_extractor.py 와 동일 의존성

    client = OpenAI()

    def _call(system: str, user: str) -> str:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        return response.choices[0].message.content or ""

    return _call, _call


def main() -> None:
    parser = argparse.ArgumentParser(description="planner SFT v3 teacher 증류")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--holdout-out", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path,
                        default=Path("outputs/planner-sft-v3-distill-cache"))
    parser.add_argument("--limit", type=int, default=0, help="스모크용 입력 제한(0=전체)")
    args = parser.parse_args()

    train_inputs, holdout_inputs = build_inputs()
    if args.limit:
        train_inputs = train_inputs[: args.limit]
    complete, judge = _openai_fns()
    result = run_distill(train_inputs, complete, judge, args.cache_dir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(result["accepted"], args.out)
    write_jsonl(holdout_inputs, args.holdout_out)
    report_path = args.out.with_suffix(".report.json")
    report_path.write_text(
        json.dumps(result["report"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[sft-v3] accepted {result['report']['accepted']}/{result['report']['total']}"
          f" -> {args.out} (드롭 사유: {report_path})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_distill.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add -f sft_pipeline/experiments/planner_sft_v3/distill_dataset.py \
           sft_pipeline/experiments/planner_sft_v3/tests/test_distill.py
git commit -m "feat(sft-v3): teacher 증류 러너 — 3단 게이트 필터·FIX 재생성·재개 캐시·드롭 리포트"
```

---

### Task 6: evaluate.py — holdout 승격 게이트 (3단 루브릭 + exit code)

**Files:**
- Create: `sft_pipeline/experiments/planner_sft_v3/evaluate.py`
- Test: `sft_pipeline/experiments/planner_sft_v3/tests/test_evaluate.py`

**Interfaces:**
- Consumes: `contract.*`, `coherence_gate.*`, holdout JSONL(Task 5 산출).
- Produces: `score_outputs(outputs: list[dict]) -> dict` — 순수 함수. 입력 `[{"input_id", "parsed_goal", "today", "raw_text", "judge_scores": dict|None}]` → `{"total", "parse_rate", "structure_violation_rate", "deadline_rate", "exam_leak", "english_leak", "semantic_avg"}`. `passes_gate(metrics: dict) -> tuple[bool, list[str]]` — 스펙 §7 임계값. 모델 로드·생성 루프는 V2 `evaluate.py`의 `_load`/`_generate` 패턴을 EXAONE으로 복제(GPU 전용 경로, 단위 테스트 밖).

**게이트 임계값(스펙 §7):** parse_rate ≥0.85, structure_violation_rate ≤0.20, exam_leak==0, english_leak==0, deadline_rate ≥0.75, semantic_avg ≥3.5.

- [ ] **Step 1: Write the failing test**

```python
# sft_pipeline/experiments/planner_sft_v3/tests/test_evaluate.py
import json

from sft_pipeline.experiments.planner_sft_v3.evaluate import passes_gate, score_outputs


def _output(raw_text, scores=None, kind="lifestyle"):
    return {
        "input_id": "x",
        "parsed_goal": {"plan_kind": kind, "goal_text": "목표", "deadline": "2026-07-20",
                        "slots": {"goal": "목표"}},
        "today": "2026-07-05",
        "raw_text": raw_text,
        "judge_scores": scores,
    }


GOOD = json.dumps({"summary_text": "차근차근 진행해요.", "days": [
    {"date": "2026-07-06", "tasks": [{"title": "상태 점검", "due_date": "2026-07-06"}]}
]}, ensure_ascii=False)


def test_score_outputs_all_good():
    metrics = score_outputs([_output(GOOD, {"M1": 4, "M2": 4, "M3": 4, "M4": 4, "average": 4.0})])
    assert metrics["parse_rate"] == 1.0
    assert metrics["structure_violation_rate"] == 0.0
    assert metrics["exam_leak"] == 0
    assert metrics["semantic_avg"] == 4.0


def test_score_outputs_counts_failures():
    bad_parse = _output("JSON 아님")
    leak = _output(json.dumps({"summary_text": "기출 위주로 준비해요.", "days": [
        {"date": "2026-07-06", "tasks": [{"title": "기출 문제 풀이", "due_date": "2026-07-06"}]}
    ]}, ensure_ascii=False), {"M1": 4, "M2": 4, "M3": 4, "M4": 4, "average": 4.0})
    metrics = score_outputs([bad_parse, leak])
    assert metrics["parse_rate"] == 0.5
    assert metrics["exam_leak"] == 1


def test_passes_gate_thresholds():
    ok = {"parse_rate": 0.9, "structure_violation_rate": 0.1, "deadline_rate": 0.8,
          "exam_leak": 0, "english_leak": 0, "semantic_avg": 3.6}
    passed, failures = passes_gate(ok)
    assert passed and failures == []

    bad = dict(ok, exam_leak=1, semantic_avg=3.2)
    passed, failures = passes_gate(bad)
    assert not passed
    assert len(failures) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_evaluate.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# sft_pipeline/experiments/planner_sft_v3/evaluate.py
"""holdout 승격 평가 — 3단 루브릭으로 측정, 스펙 §7 임계값 미달 시 exit 1.

GPU 라이브 실행(모델 생성 + judge 채점):
  uv run python -m sft_pipeline.experiments.planner_sft_v3.evaluate \
    --adapter outputs/planner-sft-v3-run1/adapter \
    --holdout sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl \
    --out outputs/planner-sft-v3-run1/eval_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sft_pipeline.experiments.planner_sft_v3 import contract
from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
    EXAM_LEAK_TERMS,
    check_structure,
    has_english_leak,
)

BASE_MODEL = "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct"

THRESHOLDS = {
    "parse_rate": ("min", 0.85),
    "structure_violation_rate": ("max", 0.20),
    "deadline_rate": ("min", 0.75),
    "exam_leak": ("max", 0),
    "english_leak": ("max", 0),
    "semantic_avg": ("min", 3.5),
}


def score_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """모델 출력 리스트 → 게이트 지표. 순수 함수(모델·네트워크 무관)."""
    total = len(outputs)
    parsed_count = 0
    violation_count = 0
    deadline_ok = 0
    exam_leak = 0
    english_leak = 0
    semantic_scores: list[float] = []

    for out in outputs:
        goal = out["parsed_goal"]
        today = date.fromisoformat(out["today"])
        try:
            plan = contract.parse_plan_output(out["raw_text"])
        except ValueError:
            continue
        parsed_count += 1

        issues = check_structure(plan, goal, today)
        if issues:
            violation_count += 1
        full_text = json.dumps(plan, ensure_ascii=False)
        if goal.get("plan_kind") != "exam" and any(t in full_text for t in EXAM_LEAK_TERMS):
            exam_leak += 1
        if has_english_leak(full_text):
            english_leak += 1
        if not any(i.startswith("S2") for i in issues):
            deadline_ok += 1
        if out.get("judge_scores"):
            semantic_scores.append(out["judge_scores"]["average"])

    return {
        "total": total,
        "parse_rate": parsed_count / total if total else 0.0,
        "structure_violation_rate": violation_count / parsed_count if parsed_count else 1.0,
        "deadline_rate": deadline_ok / parsed_count if parsed_count else 0.0,
        "exam_leak": exam_leak,
        "english_leak": english_leak,
        "semantic_avg": round(sum(semantic_scores) / len(semantic_scores), 2)
        if semantic_scores else 0.0,
    }


def passes_gate(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    failures = []
    for key, (mode, limit) in THRESHOLDS.items():
        value = metrics[key]
        ok = value >= limit if mode == "min" else value <= limit
        if not ok:
            failures.append(f"{key}={value} (기준 {mode} {limit})")
    return not failures, failures


# ── GPU 라이브 경로 (단위 테스트 밖 — V2 evaluate.py 의 _load/_generate 미러) ──

def _load(adapter: str, base_model: str):
    import torch
    from peft import PeftModel
    from torch import nn
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        base_model, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True
    )
    # EXAONE × tf5.x: peft 가 임베딩을 못 찾음 → 수동 노출 (train_plain.py 와 동일 우회)
    if not hasattr(model, "get_input_embeddings") or model.get_input_embeddings() is None:
        embedding = next(m for m in model.modules() if isinstance(m, nn.Embedding))
        model.get_input_embeddings = lambda: embedding
    if adapter and adapter != "base":
        model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model, tokenizer


def _generate(model, tokenizer, system: str, user: str, max_new_tokens: int) -> str:
    import torch

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    ids = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)
    with torch.no_grad():
        output = model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False)
    return tokenizer.decode(output[0][ids.shape[-1]:], skip_special_tokens=True).strip()


def _judge_scores_live(plan_text: str, parsed_goal: dict) -> dict | None:
    from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
        SEMANTIC_JUDGE_SYSTEM, parse_judge_reply, semantic_judge_user,
    )
    from sft_pipeline.experiments.planner_sft_v3.distill_dataset import _openai_fns

    try:
        plan = contract.parse_plan_output(plan_text)
    except ValueError:
        return None
    _, judge = _openai_fns()
    try:
        return parse_judge_reply(judge(SEMANTIC_JUDGE_SYSTEM, semantic_judge_user(plan, parsed_goal)))
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="planner SFT v3 holdout 승격 평가")
    parser.add_argument("--adapter", required=True, help="어댑터 경로 또는 'base'")
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=1200)
    args = parser.parse_args()

    holdout = [json.loads(line) for line in args.holdout.read_text(encoding="utf-8").splitlines() if line.strip()]
    model, tokenizer = _load(args.adapter, args.base_model)

    outputs = []
    for item in holdout:
        user = contract.build_user(item["parsed_goal"], date.fromisoformat(item["today"]))
        raw = _generate(model, tokenizer, contract.SYSTEM_PROMPT, user, args.max_new_tokens)
        try:
            contract.parse_plan_output(raw)
        except ValueError:
            # 운영과 동일한 재시도 1회 (스펙 §7)
            raw = _generate(model, tokenizer, contract.SYSTEM_PROMPT, user, args.max_new_tokens)
        outputs.append({
            "input_id": item["input_id"],
            "parsed_goal": item["parsed_goal"],
            "today": item["today"],
            "raw_text": raw,
            "judge_scores": _judge_scores_live(raw, item["parsed_goal"]),
        })

    metrics = score_outputs(outputs)
    passed, failures = passes_gate(metrics)
    report = {"adapter": args.adapter, "metrics": metrics, "passed": passed, "failures": failures,
              "outputs": outputs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[sft-v3] passed={passed} metrics={metrics}")
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_evaluate.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add -f sft_pipeline/experiments/planner_sft_v3/evaluate.py \
           sft_pipeline/experiments/planner_sft_v3/tests/test_evaluate.py
git commit -m "feat(sft-v3): holdout 승격 게이트 — 3단 루브릭 지표·임계값·exit code"
```

---

### Task 7: train_runpod.sh — EXAONE·train_plain 격리 학습 + 암기 가드

**Files:**
- Create: `sft_pipeline/experiments/planner_sft_v3/train_runpod.sh`

**Interfaces:**
- Consumes: Task 5 산출 `data/planner_sft_v3_gold.jsonl`·`data/holdout.jsonl`, `sft_pipeline/train/train_plain.py`, Task 6 `evaluate.py`.
- Produces: `outputs/planner-sft-v3-run{N}/{adapter,eval_report.json,train_log.txt}`.

- [ ] **Step 1: Write the script** (V2 `train_runpod.sh` 미러 + 4개 변경: train_plain·EXAONE·행수 범위·loss 가드)

```bash
#!/usr/bin/env bash
# sft_pipeline/experiments/planner_sft_v3/train_runpod.sh
set -euo pipefail

# 기존 planner LoRA 와 완전히 분리된 v3 실험. 저장소 루트에서 실행.
# EXAONE 는 unsloth 미지원 → train_plain.py (표준 transformers+peft) 사용.

DATA="${DATA:-sft_pipeline/experiments/planner_sft_v3/data/planner_sft_v3_gold.jsonl}"
HOLDOUT="${HOLDOUT:-sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl}"
EXPERIMENT_ROOT="${EXPERIMENT_ROOT:-outputs/planner-sft-v3-run1}"
TRAIN="${EXPERIMENT_ROOT}/data/train.jsonl"
VALID="${EXPERIMENT_ROOT}/data/valid.jsonl"
ADAPTER_OUT="${EXPERIMENT_ROOT}/adapter"
REPORT_OUT="${EXPERIMENT_ROOT}/eval_report.json"
TRAIN_LOG="${EXPERIMENT_ROOT}/train_log.txt"
MODEL="${MODEL:-LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct}"
EPOCHS="${EPOCHS:-1.0}"
BATCH="${BATCH:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"
LR="${LR:-2e-4}"
MEMORIZATION_FLOOR="${MEMORIZATION_FLOOR:-0.3}"   # 스펙 §6: 이보다 낮으면 암기 경고
RUN_EVAL="${RUN_EVAL:-1}"

if [ -e "${EXPERIMENT_ROOT}" ]; then
  echo "[sft-v3] ${EXPERIMENT_ROOT} 가 이미 존재합니다. 새 EXPERIMENT_ROOT 를 지정하세요."
  exit 1
fi
for file in "${DATA}" "${HOLDOUT}" sft_pipeline/train/train_plain.py \
  sft_pipeline/experiments/planner_sft_v3/evaluate.py; do
  [ -f "${file}" ] || { echo "[sft-v3] 누락: ${file}"; exit 1; }
done

python3 - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("[sft-v3] CUDA GPU가 필요합니다")
print("[sft-v3] GPU:", torch.cuda.get_device_name(0))
PY

ROWS="$(grep -cve '^[[:space:]]*$' "${DATA}")"
if [ "${ROWS}" -lt 700 ] || [ "${ROWS}" -gt 1000 ]; then
  echo "[sft-v3] 데이터는 700~1000건이어야 합니다(증류 필터 후): 실제 ${ROWS}건"
  exit 1
fi

mkdir -p "${EXPERIMENT_ROOT}/data"
python3 -m pip install -U pip
python3 -m pip install -r sft_pipeline/train/requirements.txt

python3 -m sft_pipeline.build.lib.validate_dataset --in "${DATA}"
python3 -m sft_pipeline.build.lib.split_dataset \
  --in "${DATA}" --out-train "${TRAIN}" --out-valid "${VALID}" \
  --ratio 0.9 --seed 42
python3 -m sft_pipeline.build.lib.validate_dataset --in "${TRAIN}"
python3 -m sft_pipeline.build.lib.validate_dataset --in "${VALID}"

# tmux 안에서 실행 권장 (SSH 끊김 = SIGKILL). 재실행은 HF_HUB_OFFLINE=1.
python3 -m sft_pipeline.train.train_plain \
  --train "${TRAIN}" --valid "${VALID}" --out "${ADAPTER_OUT}" \
  --model "${MODEL}" --epochs "${EPOCHS}" \
  --batch "${BATCH}" --grad-accum "${GRAD_ACCUM}" --lr "${LR}" \
  2>&1 | tee "${TRAIN_LOG}"

# 암기 경고 가드(스펙 §6): 마지막 train_loss 가 바닥보다 낮으면 승격 금지
FINAL_LOSS="$(grep -oE "'loss': [0-9.]+" "${TRAIN_LOG}" | tail -1 | grep -oE '[0-9.]+' || echo '')"
if [ -n "${FINAL_LOSS}" ]; then
  python3 - "$FINAL_LOSS" "$MEMORIZATION_FLOOR" <<'PY'
import sys
loss, floor = float(sys.argv[1]), float(sys.argv[2])
print(f"[sft-v3] final train_loss={loss}")
if loss < floor:
    raise SystemExit(f"[sft-v3] 암기 경고: train_loss {loss} < {floor} — 데이터 다양성 재점검 후 재학습 (스펙 §6)")
PY
else
  echo "[sft-v3] 경고: train_loss 를 로그에서 찾지 못함 — ${TRAIN_LOG} 수동 확인 필요"
fi

if [ "${RUN_EVAL}" = "1" ]; then
  python3 -m sft_pipeline.experiments.planner_sft_v3.evaluate \
    --adapter "${ADAPTER_OUT}" --base-model "${MODEL}" \
    --holdout "${HOLDOUT}" --out "${REPORT_OUT}"
else
  echo "[sft-v3] RUN_EVAL=0: 평가 생략 — 배포 승격에 사용 금지"
fi

echo "[sft-v3] 완료 — 어댑터 즉시 S3 백업 필수 (Pod ephemeral):"
echo "  tar czf exaone-planner-sft-v3.tgz -C ${ADAPTER_OUT} . && aws s3 cp ..."
```

- [ ] **Step 2: Verify script syntax and guard logic offline**

Run: `bash -n sft_pipeline/experiments/planner_sft_v3/train_runpod.sh && echo OK`
Expected: `OK`

Run (loss 가드 단독 검증):
```bash
python3 - 0.079 0.3 <<'PY'
import sys
loss, floor = float(sys.argv[1]), float(sys.argv[2])
if loss < floor:
    raise SystemExit(f"암기 경고: {loss} < {floor}")
PY
```
Expected: exit code 1, `암기 경고: 0.079 < 0.3`

- [ ] **Step 3: Commit**

```bash
chmod +x sft_pipeline/experiments/planner_sft_v3/train_runpod.sh
git add -f sft_pipeline/experiments/planner_sft_v3/train_runpod.sh
git commit -m "feat(sft-v3): EXAONE train_plain 격리 학습 스크립트 + 암기 loss 가드"
```

---

### Task 8: A/B 노트북 빌더 + README (실행·승격·롤백 절차)

**Files:**
- Create: `sft_pipeline/experiments/planner_sft_v3/build_ab_notebook.py`
- Create: `sft_pipeline/experiments/planner_sft_v3/README.md`
- Test: `sft_pipeline/experiments/planner_sft_v3/tests/test_ab_notebook.py`

**Interfaces:**
- Consumes: `evaluate.score_outputs`·`passes_gate`·`_load`·`_generate`·`_judge_scores_live`, holdout JSONL.
- Produces: `build_notebook(out: Path) -> None` → `ab_test.ipynb` — 같은 holdout을 `adapter="base"`와 v3 어댑터로 각각 생성·채점해 지표 표+판정 셀을 출력. **실행 후 출력이 박힌 노트북을 커밋하는 것이 승격 관문**(스펙 §7). 빌더 패턴은 `scripts/build_routine_eval_notebook.py` 선례(생성 후 `nbconvert --execute --inplace`).

- [ ] **Step 1: Write the failing test**

```python
# sft_pipeline/experiments/planner_sft_v3/tests/test_ab_notebook.py
import json

from sft_pipeline.experiments.planner_sft_v3.build_ab_notebook import build_notebook


def test_notebook_structure(tmp_path):
    out = tmp_path / "ab_test.ipynb"
    build_notebook(out)
    nb = json.loads(out.read_text(encoding="utf-8"))
    sources = "".join("".join(c["source"]) for c in nb["cells"])
    # base 와 adapter 양쪽 실행 + 판정 셀이 있어야 함
    assert '"base"' in sources
    assert "score_outputs" in sources and "passes_gate" in sources
    assert "semantic_avg" in sources  # LoRA ≥ base 판정 (스펙 §7)
    assert nb["nbformat"] == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/test_ab_notebook.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# sft_pipeline/experiments/planner_sft_v3/build_ab_notebook.py
"""base vs v3 LoRA A/B 노트북 생성기.

생성 후 GPU pod 에서 실행·출력 임베드(승격 관문, 스펙 §7):
  uv run python -m sft_pipeline.experiments.planner_sft_v3.build_ab_notebook
  jupyter nbconvert --to notebook --execute --inplace \
    sft_pipeline/experiments/planner_sft_v3/ab_test.ipynb
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_OUT = Path("sft_pipeline/experiments/planner_sft_v3/ab_test.ipynb")


def _code(source: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": source.splitlines(keepends=True)}


def _md(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


_CELLS = [
    _md("# Planner SFT v3 — base vs LoRA A/B\n같은 holdout 30건을 두 모델로 생성·채점한다. "
        "**출력이 박힌 이 노트북의 커밋이 승격 관문이다** (스펙 §7)."),
    _code("""import sys, json
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))  # 저장소 루트에서 실행

from sft_pipeline.experiments.planner_sft_v3 import contract
from sft_pipeline.experiments.planner_sft_v3.evaluate import (
    BASE_MODEL, _generate, _judge_scores_live, _load, passes_gate, score_outputs,
)

ADAPTER = "outputs/planner-sft-v3-run1/adapter"  # 평가 대상 어댑터
HOLDOUT = Path("sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl")
holdout = [json.loads(l) for l in HOLDOUT.read_text(encoding="utf-8").splitlines() if l.strip()]
print(f"holdout {len(holdout)}건")"""),
    _code("""def run(adapter_name):
    model, tok = _load(adapter_name, BASE_MODEL)
    outs = []
    for item in holdout:
        user = contract.build_user(item["parsed_goal"], date.fromisoformat(item["today"]))
        raw = _generate(model, tok, contract.SYSTEM_PROMPT, user, 1200)
        outs.append({"input_id": item["input_id"], "parsed_goal": item["parsed_goal"],
                     "today": item["today"], "raw_text": raw,
                     "judge_scores": _judge_scores_live(raw, item["parsed_goal"])})
    del model
    import torch; torch.cuda.empty_cache()
    return outs

base_outputs = run("base")
lora_outputs = run(ADAPTER)"""),
    _code("""base_metrics = score_outputs(base_outputs)
lora_metrics = score_outputs(lora_outputs)
print("base:", json.dumps(base_metrics, ensure_ascii=False, indent=2))
print("lora:", json.dumps(lora_metrics, ensure_ascii=False, indent=2))"""),
    _code("""lora_passed, failures = passes_gate(lora_metrics)
semantic_win = lora_metrics["semantic_avg"] >= base_metrics["semantic_avg"]
promote = lora_passed and semantic_win
print(f"게이트 통과: {lora_passed} (미달: {failures})")
print(f"의미 평균 LoRA {lora_metrics['semantic_avg']} vs base {base_metrics['semantic_avg']}"
      f" -> {'우위' if semantic_win else '열세'}")
print(f"\\n최종 판정: {'승격 자격' if promote else '기각 — 수치와 함께 기록'}")"""),
    _code("""# 케이스별 나란히 비교 (처음 5건)
for b, l in list(zip(base_outputs, lora_outputs))[:5]:
    print("=" * 60)
    print("목표:", b["parsed_goal"]["goal_text"])
    print("[base]", b["raw_text"][:300])
    print("[lora]", l["raw_text"][:300])"""),
]


def build_notebook(out: Path = _DEFAULT_OUT) -> None:
    nb = {"cells": _CELLS, "metadata": {"language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[sft-v3] wrote {out}")


if __name__ == "__main__":
    build_notebook()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/ -v`
Expected: 전체 PASS (전 태스크 회귀 포함)

- [ ] **Step 5: Write README**

````markdown
# Planner SFT v3 — teacher 증류 재시도

스펙: `docs/superpowers/specs/2026-07-04-planner-sft-v3-design.md`.
기존 운영 어댑터·`LORA_PLANNER_REPO`·V2 디렉토리는 절대 수정하지 않는다.

## 실행 순서 (저장소 루트에서)

1. **오프라인 테스트**: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/ -v`
2. **증류 (비용 발생, OPENAI_API_KEY 필요)**:
   ```bash
   uv run python -m sft_pipeline.experiments.planner_sft_v3.distill_dataset \
     --out sft_pipeline/experiments/planner_sft_v3/data/planner_sft_v3_gold.jsonl \
     --holdout-out sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl
   ```
   중단돼도 재실행하면 캐시(`outputs/planner-sft-v3-distill-cache/`)에서 재개.
   먼저 `--limit 20` 스모크로 드롭 사유 분포를 확인하고 teacher 프롬프트를 조정할 것.
3. **학습 (RunPod 24GB, tmux 안에서)**:
   ```bash
   EXPERIMENT_ROOT=outputs/planner-sft-v3-run1 \
   bash sft_pipeline/experiments/planner_sft_v3/train_runpod.sh
   ```
   train_loss < 0.3 이면 스크립트가 중단한다(암기 경고). 어댑터는 즉시 S3 백업.
4. **A/B 관문**: `build_ab_notebook.py` 로 노트북 생성 → GPU pod 에서
   `jupyter nbconvert --execute --inplace` → **출력 박힌 노트북을 `git add -f` 커밋**.

## 승격 기준 (스펙 §7·§9)

- `eval_report.json` 의 게이트 전부 통과 **그리고** A/B 의미 평균 LoRA ≥ base → 승격 자격.
- 미달이면 기각 — eval_report 와 A/B 노트북이 곧 기각 근거 기록이다. 재학습은
  드롭 사유 분포(`*.report.json`)를 보고 데이터부터 고친 뒤에만.

## 승격 절차 (통과 시에만)

V2 README §5~§6 절차 그대로: 신규 HF repo `bigmooon/exaone-planner-sft-v3` 업로드 →
RunPod 템플릿 복제 테스트 엔드포인트 → 문제 없으면 운영 `LORA_PLANNER_REPO` 변경.
롤백 = env 원복.

## 함정

- `sft_pipeline/` 은 `.gitignore` — 신규 파일은 항상 `git add -f`.
- Pod 재실행은 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`.
- 스모크·평가는 학습 *후*에만 (커널이 VRAM 물면 학습 OOM).
````

- [ ] **Step 6: Commit**

```bash
git add -f sft_pipeline/experiments/planner_sft_v3/build_ab_notebook.py \
           sft_pipeline/experiments/planner_sft_v3/README.md \
           sft_pipeline/experiments/planner_sft_v3/tests/test_ab_notebook.py
git commit -m "feat(sft-v3): base vs LoRA A/B 노트북 빌더 + 실행·승격·롤백 README"
```

---

## 이후 수동 단계 (코드 밖 — 사용자 실행)

1. `--limit 20` 증류 스모크 → 드롭 사유 분포 확인 → 전체 증류 (~935 teacher 호출 + judge 호출, 수만 원).
2. RunPod에서 학습 → loss 가드 통과 확인 → 어댑터 S3 백업.
3. `evaluate.py` + A/B 노트북 실행 → 출력 커밋 → 승격/기각 판정.
4. 판정 결과를 CHANGELOG에 기록 (승격이든 기각이든).
