# 일상 멀티턴 플래너 — Phase 2A Implementation Plan (plan_generator 뉴로-심볼릭 분업 완성)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `plan_generator` 를 **0단계 용량 선계산(코드) → 1단계 LLM(N개 task + 순서/상대배치) → 2단계 코드(마감 앵커 매핑 + clamp + 용량검사) → critic 검증(+우겨넣기 차단)** 로 분업해, 일상 정합 플랜(P2)을 작은 모델 과부하 없이 생성한다.

**Architecture:** 설계서 §3.4(D8)·§3.5(LLM-Modulo critic). **미러-안전 브릿지:** 배포된 모델은 여전히 절대 날짜 `days` 를 방출하므로, 2A 의 2단계는 모델 출력의 **순서(order)** 만 신뢰해 deadline 앵커로 재매핑한다(§4.3 "date 필드는 상대 순서 신호로 재해석"). 따라서 2A 는 **재학습(2C) 없이 현재 모델과 동작**하고, 2C 의 rel_day SFT 와도 forward-compatible. critic 은 `sft_pipeline` 을 import 하지 않고 **런타임 미러 + 동기화 테스트**(스키마 미러와 동일 패턴)로 둔다.

**Tech Stack:** Python, LangGraph, pytest(asyncio_mode=auto), uv. 린트 `uvx ruff check`.

**근거 스펙:** `docs/superpowers/specs/2026-06-14-daily-life-planner-design.md` §3.4, §3.5, §4.3, D8.

**선행 조건:** **Phase 1 (PR #91) 가 main 에 머지된 뒤** 이 브랜치를 main 에서 분기해 시작한다. Phase 1 의 `allocator.py`(`expand_routine`)·`slot_schemas`·plan_kind 분류에 의존한다.

---

## 현재 코드 앵커 (구현 전 반드시 확인)

- `agents/todo_creation/planner/nodes/plan_generator.py` — `plan_generator_node`. 현재: `generate_plan`(절대날짜 `days`) → `_prepare_plan_days`(날짜 정리·동일목표면 today부터 spread) → `_clamp_to_deadline`(Phase 0 P1) → today==due_date 로 todos/events 분리. **2A 가 _prepare_plan_days 의 today-순차 spread 를 deadline-앵커 매핑으로 교체**한다.
- `agents/todo_creation/planner/allocator.py` — Phase 1 `expand_routine` + `_parse_weekdays`. 여기에 `compute_capacity` 와 `map_ordered_to_dates` 를 추가한다(같은 도메인 = 같은 파일).
- `adapters/todo_creation/qwen_llm.py:351` — `generate_plan(*, parsed_goal, today) -> tuple[str, list[PlanDay]]`. `_complete_json_with_retry` 로 `{summary_text, days:[{date,tasks}], personalization_patch}` 파싱. **반환 형태(절대 PlanDay)는 유지**하되, 0단계 N 을 프롬프트 힌트로 전달(Task 5).
- `adapters/todo_creation/_prompts.py:164` — `PLAN_GENERATOR_SYSTEM` + `plan_generator_user(*, parsed_goal, today)`.
- `sft_pipeline/build/plan_schemas.py` — `check_plan_consistency`(+ `PlanOutput`/`PlanTask` 미러). **런타임에서 import 금지**(결합 방지 규율). 규칙: today≤due_date≤today+horizon, due_date==today→todos, 1≤개수≤50, 단조분해 제목 과반 reject. 2A 의 런타임 critic 은 이를 **미러**하고 동기화 테스트로 묶는다.
- `agents/todo_creation/planner/graph.py` — `plan_generator` 노드는 `add_edge("plan_generator", END)`. critic 재시도는 **노드 내부 루프**(LLM 0~1회 재호출)로 두어 토폴로지 변화 0 (§3.5 "토폴로지 변화 최소").

---

## 파일 구조

- **Modify:** `agents/todo_creation/planner/allocator.py` — `compute_capacity()`, `map_ordered_to_dates()` 추가.
- **Create:** `agents/todo_creation/planner/plan_critic.py` — 런타임 `check_plan_consistency()` 미러 + 위반 사유.
- **Create:** `tests/agents/todo_creation/planner/test_plan_critic_mirror.py` — SFT critic 규칙과 동기화(동일 입력→동일 판정) 테스트.
- **Modify(설계 후):** `agents/todo_creation/planner/nodes/plan_generator.py` — 0→1→2→critic 파이프라인으로 재구성, `_prepare_plan_days` 의 spread 를 `map_ordered_to_dates` 로 교체.
- **Modify(설계 후):** `_prompts.py`(`PLAN_GENERATOR_SYSTEM`/`plan_generator_user`) — 목표 개수 N 힌트 + "마감/리듬 고려 순서" 지시. (라이브 프롬프트.)
- **Modify(설계 후):** cram 처리 — flexible(routine/lifestyle)=개수 축소 재실행, fixed(exam)=사용자 통지 메시지.

---

## Task 1: 0단계 — 용량 선계산 `compute_capacity` (완전 TDD)

**Files:**
- Modify: `agents/todo_creation/planner/allocator.py`
- Test: `tests/agents/todo_creation/planner/test_compute_capacity.py`

남은 일수 × 하루 가용 슬롯 → 목표 task 개수 N. deadline 있으면 today..deadline, 없으면 horizon. 하루 가용은 `daily_capacity_minutes` 기반(없으면 기본 1슬롯/일).

- [ ] **Step 1: 실패 테스트**

`tests/agents/todo_creation/planner/test_compute_capacity.py`:

```python
from datetime import date

from agents.todo_creation.planner.allocator import compute_capacity


def test_capacity_uses_days_to_deadline() -> None:
    # today..deadline 포함 7일, 하루 1슬롯 기본 → 약 7
    n = compute_capacity(
        {"deadline": date(2026, 6, 21)}, today=date(2026, 6, 15), slots_per_day=1
    )
    assert n == 7


def test_capacity_falls_back_to_horizon_without_deadline() -> None:
    n = compute_capacity({}, today=date(2026, 6, 15), horizon_days=28, slots_per_day=1)
    assert n == 28


def test_capacity_scales_with_daily_minutes() -> None:
    # 하루 240분 / 120분당 1슬롯 = 2슬롯/일 × 3일(15,16,17) = 6
    n = compute_capacity(
        {"deadline": date(2026, 6, 17), "daily_capacity_minutes": 240},
        today=date(2026, 6, 15),
        minutes_per_slot=120,
    )
    assert n == 6


def test_capacity_at_least_one() -> None:
    assert compute_capacity({"deadline": date(2026, 6, 15)}, today=date(2026, 6, 15)) >= 1
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/agents/todo_creation/planner/test_compute_capacity.py -v --no-cov` → ImportError.

- [ ] **Step 3: 구현** — `allocator.py` 에 추가:

```python
_DEFAULT_HORIZON = 28
_DEFAULT_SLOTS_PER_DAY = 1


def compute_capacity(
    parsed_goal: dict,
    *,
    today: date,
    horizon_days: int = _DEFAULT_HORIZON,
    slots_per_day: int | None = None,
    minutes_per_slot: int = 120,
) -> int:
    """남은 일수 × 하루 가용 슬롯 → 목표 task 개수 N (최소 1)."""
    deadline = parsed_goal.get("deadline")
    if isinstance(deadline, date):
        span_days = (deadline - today).days + 1
    else:
        span_days = horizon_days
    span_days = max(1, span_days)

    if slots_per_day is None:
        minutes = parsed_goal.get("daily_capacity_minutes")
        if isinstance(minutes, int) and minutes > 0:
            slots_per_day = max(1, minutes // minutes_per_slot)
        else:
            slots_per_day = _DEFAULT_SLOTS_PER_DAY

    return max(1, span_days * slots_per_day)
```

- [ ] **Step 4: 통과 + 린트** — `uv run pytest .../test_compute_capacity.py -v --no-cov && uvx ruff check agents/todo_creation/planner/allocator.py`

- [ ] **Step 5: 커밋**
```bash
git add agents/todo_creation/planner/allocator.py tests/agents/todo_creation/planner/test_compute_capacity.py
git commit -m "feat: 0단계 용량 선계산 compute_capacity (Phase 2A, §3.4)"
```

---

## Task 2: 2단계 — 마감 앵커 매핑 `map_ordered_to_dates` (완전 TDD)

**Files:**
- Modify: `agents/todo_creation/planner/allocator.py`
- Test: `tests/agents/todo_creation/planner/test_map_ordered_to_dates.py`

LLM 이 만든 **순서대로의 task 목록**(절대날짜 무시)을 받아, deadline 을 하드 앵커로 today..deadline 에 매핑한다. **재배열·균등화 없음**(순서 보존). deadline 없으면 today 부터 horizon 내 순차. clamp(마감 이후 금지) + 하루 용량 초과 차단.

- [ ] **Step 1: 실패 테스트**

`tests/agents/todo_creation/planner/test_map_ordered_to_dates.py`:

```python
from datetime import date

from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.planner.allocator import map_ordered_to_dates


def _tasks(*titles: str) -> list[TaskCandidate]:
    return [TaskCandidate(title=t, due_date=date(2026, 1, 1)) for t in titles]


def test_anchors_within_deadline_in_order() -> None:
    # 3개 task, deadline 6/17, today 6/15 → today 부터 순서대로, 마감 이내
    out = map_ordered_to_dates(
        _tasks("개념", "문제풀이", "시험"),
        today=date(2026, 6, 15),
        deadline=date(2026, 6, 17),
    )
    dates = [t.due_date for t in out]
    assert dates == [date(2026, 6, 15), date(2026, 6, 16), date(2026, 6, 17)]


def test_preserves_order_no_resort() -> None:
    out = map_ordered_to_dates(
        _tasks("B", "A"), today=date(2026, 6, 15), deadline=date(2026, 6, 16)
    )
    assert [t.title for t in out] == ["B", "A"]


def test_clamps_tasks_beyond_deadline() -> None:
    # 5개인데 deadline 까지 3일 → 마감 이후로 밀리는 것은 제거(clamp)
    out = map_ordered_to_dates(
        _tasks("1", "2", "3", "4", "5"),
        today=date(2026, 6, 15),
        deadline=date(2026, 6, 17),
        slots_per_day=1,
    )
    assert all(t.due_date <= date(2026, 6, 17) for t in out)
    assert len(out) == 3


def test_no_deadline_sequential_from_today() -> None:
    out = map_ordered_to_dates(
        _tasks("a", "b"), today=date(2026, 6, 15), deadline=None
    )
    assert [t.due_date for t in out] == [date(2026, 6, 15), date(2026, 6, 16)]
```

- [ ] **Step 2: 실패 확인** — ImportError.

- [ ] **Step 3: 구현** — `allocator.py` 에 추가:

```python
def map_ordered_to_dates(
    tasks: list,
    *,
    today: date,
    deadline: date | None,
    horizon_days: int = _DEFAULT_HORIZON,
    slots_per_day: int = _DEFAULT_SLOTS_PER_DAY,
) -> list:
    """순서 보존 task 목록을 today.. 에 하루 slots_per_day 개씩 매핑(마감 이후 clamp)."""
    end = deadline if deadline is not None else today + timedelta(days=horizon_days - 1)
    mapped = []
    day = today
    used_today = 0
    for task in tasks:
        if day > end:
            break  # clamp: 마감/horizon 이후 금지
        mapped.append(task.model_copy(update={"due_date": day}))
        used_today += 1
        if used_today >= slots_per_day:
            day = day + timedelta(days=1)
            used_today = 0
    return mapped
```

> ⚠️ **설계 노트(Step 3 구현자 확인):** 위는 "앞에서부터 깔기 + clamp" 의 단순형이다. 설계서 §3.4 의 "마감일=하드 앵커(마지막 날 고정)" 를 엄밀히 지키려면 task 수 < 남은일수일 때 뒤에서부터 deadline 에 붙이는 변형이 필요하다. **구현 직전 둘 중 하나를 선택**하고(앞채움+clamp = 단순·P1 안전 / 뒤채움 앵커 = 마감 밀착) 테스트를 그에 맞춘다. 기본 권장: 앞채움+clamp(테스트 위와 같음, P1 보장 단순). exam deadline 이벤트의 "deadline 당일 배치"는 Task 4 의 critic/배치에서 보강.

- [ ] **Step 4: 통과 + 린트**
- [ ] **Step 5: 커밋** — `feat: 2단계 마감 앵커 매핑 map_ordered_to_dates (Phase 2A, §3.4)`

---

## Task 3: 런타임 critic 미러 `plan_critic.py` (완전 TDD + 동기화 테스트)

**Files:**
- Create: `agents/todo_creation/planner/plan_critic.py`
- Test: `tests/agents/todo_creation/planner/test_plan_critic.py`
- Test: `tests/agents/todo_creation/planner/test_plan_critic_mirror.py` (SFT 규칙과 동기화)

`sft_pipeline` 을 import 하지 않고 동일 규칙을 런타임에 둔다. 규칙: ① today≤due_date≤today+horizon ② due_date==today→todos·미래→events 분기 적합 ③ 1≤개수 ④ deadline 알려지면 due_date>deadline 금지(P1) ⑤ 하루 항목 수 ≤ 용량(cram 차단). 반환: `(ok: bool, violations: list[str])`.

- [ ] **Step 1: 실패 테스트** (`test_plan_critic.py`)

```python
from datetime import date

from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.planner.plan_critic import check_plan_consistency


def _t(title, d):
    return TaskCandidate(title=title, due_date=d)


def test_ok_within_deadline() -> None:
    ok, violations = check_plan_consistency(
        [_t("a", date(2026, 6, 15)), _t("b", date(2026, 6, 16))],
        today=date(2026, 6, 15),
        deadline=date(2026, 6, 17),
        slots_per_day=1,
    )
    assert ok and violations == []


def test_rejects_task_after_deadline() -> None:
    ok, violations = check_plan_consistency(
        [_t("late", date(2026, 6, 20))],
        today=date(2026, 6, 15),
        deadline=date(2026, 6, 17),
        slots_per_day=1,
    )
    assert not ok
    assert any("deadline" in v for v in violations)


def test_rejects_capacity_overflow() -> None:
    # 하루 1슬롯인데 같은 날 2개 → cram
    ok, violations = check_plan_consistency(
        [_t("a", date(2026, 6, 15)), _t("b", date(2026, 6, 15))],
        today=date(2026, 6, 15),
        deadline=date(2026, 6, 17),
        slots_per_day=1,
    )
    assert not ok
    assert any("용량" in v or "capacity" in v for v in violations)
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — `plan_critic.py`. 규칙 ①~⑤ 를 순수 함수로. (horizon·C5·단조분해는 SFT `plan_schemas._task_errors` 와 같은 취지로 작성. 정확한 규칙 텍스트는 구현 직전 `sft_pipeline/build/plan_schemas.py` 의 `check_plan_consistency`/`_task_errors` 를 읽어 1:1 미러.)
- [ ] **Step 4: 동기화 테스트** (`test_plan_critic_mirror.py`) — 동일한 (plan, today, horizon) 입력에 대해 런타임 `plan_critic` 과 SFT `sft_pipeline.build.plan_schemas` 의 판정(ok/위반 유무)이 일치함을 확인. (스키마 미러의 `test_mirror_matches_runtime_schema` 와 동형. 이 테스트만 `sft_pipeline` 을 import 한다 — 테스트는 양쪽을 아는 게 정상.)
- [ ] **Step 5: 통과 + 린트 + 커밋** — `feat: 런타임 plan_critic 미러 + 동기화 테스트 (Phase 2A, §3.5)`

---

## Task 4 (설계 후 구현): `plan_generator_node` 분업 파이프라인 재구성

> ⚠️ 0→1→2→critic 배선 + cram 분기는 **노드 내부 구조 결정**(self-loop 재실행 조건, flexible 축소 vs fixed 통지 경로)을 포함한다. 구현 직전 짧은 설계 패스로 확정한 뒤 아래 인터페이스·수용 테스트에 맞춘다.

**인터페이스(불변):** `plan_generator_node(state, config) -> dict` 그대로. 내부만 교체:
1. `N = compute_capacity(parsed_goal, today)`.
2. `summary, days = generate_plan(parsed_goal, today, target_count=N)` — 모델 출력의 **순서**만 사용(절대날짜 무시).
3. `ordered = [task for day in days for task in day.tasks]` (모델 순서) → `mapped = map_ordered_to_dates(ordered, today=today, deadline=parsed_goal.deadline, slots_per_day=...)`.
4. `ok, violations = check_plan_consistency(mapped, today=today, deadline=..., slots_per_day=...)`.
5. **cram 처리(§3.5):** 용량 초과면 — flexible(routine/lifestyle)=개수 축소 후 2단계 재실행(LLM 0회), fixed(exam)=`summary_text` 에 "기간이 빠듯" 통지(또는 follow_up). 통과까지 ≤2회.
6. today==due_date→todos / 그 외→events (기존 분기 유지). `_prepare_plan_days` 의 today-순차 spread 제거.

**수용 테스트(페이크 LLM, 결정론):**
- exam + deadline → 플랜 마지막 task 가 deadline 이내, 마감 이후 0개(P1 회귀).
- 모델이 용량 초과 개수를 내면 → routine 은 축소되어 critic 통과, exam 은 통지 문구 포함.
- 모델이 절대날짜를 뒤죽박죽 줘도 → 순서 보존 매핑(2단계가 재앵커).

설계서 §3.4·§3.5, 성공기준 P2. **TDD:** 페이크 LLM 으로 days 고정 → 매핑·clamp·critic 분기 단위 검증.

---

## Task 5 (설계 후 구현): `PLAN_GENERATOR_SYSTEM` + `generate_plan` N 힌트

> ⚠️ 라이브 프롬프트 변경. **미러-안전:** 출력 JSON 형태(`{summary_text, days:[{date,tasks}]}`)는 **유지**한다(배포 모델 호환). 추가는 (a) user 프롬프트에 "목표 task 개수 ≈ N" 힌트, (b) system 에 "마감·리듬(개념→복습) 고려해 **순서대로** 배치, 절대 날짜 정확도는 불필요(코드가 재계산)" 지시.

**변경:** `generate_plan(*, parsed_goal, today, target_count: int | None = None)` 시그니처 확장(기본 None=기존 거동). `plan_generator_user` 에 N 힌트 문자열 추가. `PLAN_GENERATOR_SYSTEM` 에 순서/리듬 지시 1~2줄.

**수용 테스트(페이크 호환):** target_count 가 user 프롬프트에 포함됨. 기존 generate_plan 테스트(절대날짜 days 파싱) 무회귀.

설계서 §3.4 1단계. **SFT 미러 주의:** 이 프롬프트는 SFT 미러 대상이 아님(`judge`/`plan` 생성 프롬프트는 런타임 전용, plan **타깃** 형식만 미러). 단 2C 에서 plan 타깃을 task목록+rel_day 로 전환할 때 이 프롬프트와 정합 맞춤.

---

## Phase 2A 완료 기준 (DoD)

- [ ] `compute_capacity` 가 deadline/horizon·daily_minutes 로 N 산출 (Task 1).
- [ ] `map_ordered_to_dates` 가 순서 보존 + 마감 앵커 + clamp (Task 2).
- [ ] 런타임 `plan_critic` 가 SFT 규칙 미러 + 동기화 테스트 통과 (Task 3).
- [ ] `plan_generator_node` 가 0→1→2→critic 분업 + cram 차단(flexible 축소/fixed 통지) (Task 4).
- [ ] 프롬프트 N 힌트 + 순서 배치 지시, 출력 형태 미러-안전 유지 (Task 5).
- [ ] 그래프 토폴로지·`GenerateResult` 미러·state 스키마 불변. P1 회귀 없음. 배포 모델(절대날짜 출력)과 호환.

---

## Self-Review (작성자 체크)

- **스펙 커버리지:** Task 1–3 은 §3.4(0·2단계)·§3.5(critic)를 완전 코드로 커버. Task 4–5 는 §3.4 1단계·cram 분기·라이브 프롬프트라 "설계 후 구현"(인터페이스+수용 테스트)로 스코프.
- **미러-안전:** 모델 출력 형태 불변 + 순서만 재해석 → 재학습 없이 동작. critic 은 sft import 없이 미러+동기화(코드베이스 규율 준수).
- **타입 일관성:** `compute_capacity`/`map_ordered_to_dates`/`check_plan_consistency` 시그니처가 Task 4 사용처와 일치. `slots_per_day` 의미가 세 함수에서 동일(하루 가용 슬롯).
- **선행 의존:** Phase 1 머지 후 시작(allocator 확장, slot_schemas plan_kind 로 flexible/fixed 분기).
- **2C 연결:** 2A 의 2단계 매핑이 2C 의 rel_day SFT 타깃과 호환(순서=rel_day). lifestyle 내용 품질은 2B(라이브러리) 후 Task 4 의 1단계 입력으로 합류.
