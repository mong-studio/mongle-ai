# 일상 멀티턴 플래너 — Phase 0 Implementation Plan (P1 핫픽스)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "일주일 뒤 시험"류 입력에서 마감일 이후에 task(회고 등)가 붙는 P1 버그를, 런타임 deadline clamp + 프롬프트 배치 지시로 막는다.

**Architecture:** 설계서 §3.4·§3.5·§9의 뉴로-심볼릭 분업 중 **Phase 0만** 구현한다. 큰 구조(스키마 뱅크·allocator·SFT)는 건드리지 않고, 기존 `plan_generator_node`에 **결정적 deadline clamp**(코드, 마감 이후 task 제거)와 **프롬프트의 상대-배치/마감-앵커 지시**만 더한다. clamp 규칙은 Phase 2 매핑에서도 승계되는 영구물이라 버려지는 코드가 없다.

**Tech Stack:** Python, LangGraph(기존), pytest(asyncio_mode=auto), uv.

**근거 스펙:** `docs/superpowers/specs/2026-06-14-daily-life-planner-design.md` (D8, §3.4, §3.5, §9 Phase 0)

---

## 파일 구조 (Phase 0이 건드리는 것)

- **Modify:** `agents/todo_creation/planner/nodes/plan_generator.py` — `plan_generator_node`에 deadline clamp 단계 추가 + `_clamp_to_deadline` 헬퍼 신규.
- **Modify:** `adapters/todo_creation/_prompts.py` — plan 생성 프롬프트에 "마감일 = 마지막 날, 마감 이후 task 금지, 상대 배치로 리듬" 지시 추가.
- **Test:** `tests/agents/todo_creation/planner/nodes/test_plan_generator.py` — clamp 동작 + P1 회귀 테스트 추가.

**불변:** 그래프 토폴로지, `GenerateResult`/`PlanOutput` 미러, state 스키마, SFT 파이프라인. (SFT측 `check_plan_consistency`는 이미 `due_date > horizon` 금지 규칙이 있어 Phase 0에서 코드 변경 불필요 — Task 4에서 확인만 한다.)

---

## Task 1: 런타임 deadline clamp (`_clamp_to_deadline`)

**Files:**
- Modify: `agents/todo_creation/planner/nodes/plan_generator.py`
- Test: `tests/agents/todo_creation/planner/nodes/test_plan_generator.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/agents/todo_creation/planner/nodes/test_plan_generator.py` 끝에 추가 (파일 상단에 `from datetime import timedelta` 이미 있음):

```python
async def test_drops_tasks_after_deadline() -> None:
    """parsed_goal.deadline 이후 날짜의 task 는 제거한다 (P1)."""
    deadline = _TODAY + timedelta(days=2)
    d0 = TaskCandidate(title="개념", due_date=_TODAY)
    d1 = TaskCandidate(title="기출", due_date=_TODAY + timedelta(days=1))
    after = TaskCandidate(title="회고", due_date=_TODAY + timedelta(days=3))  # 마감 이후
    plan: list[PlanDay] = [
        {"date": _TODAY, "tasks": [d0]},
        {"date": _TODAY + timedelta(days=1), "tasks": [d1]},
        {"date": _TODAY + timedelta(days=3), "tasks": [after]},
    ]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(
        _state({"goal_tag": "목표", "deadline": deadline}), _config(llm)
    )

    titles = [t.title for t in result["todos"] + result["calendar_events"]]
    assert "회고" not in titles
    assert "개념" in titles
    assert "기출" in titles


async def test_keeps_all_tasks_when_no_deadline() -> None:
    """deadline 이 없으면 clamp 하지 않는다 (기존 거동 보존)."""
    after = TaskCandidate(title="회고", due_date=_TODAY + timedelta(days=3))
    plan: list[PlanDay] = [{"date": _TODAY + timedelta(days=3), "tasks": [after]}]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(_state({"goal_tag": "목표"}), _config(llm))

    titles = [t.title for t in result["todos"] + result["calendar_events"]]
    assert "회고" in titles
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/agents/todo_creation/planner/nodes/test_plan_generator.py::test_drops_tasks_after_deadline -v`
Expected: FAIL — "회고" 가 여전히 결과에 포함됨 (clamp 미구현).

- [ ] **Step 3: 최소 구현**

`agents/todo_creation/planner/nodes/plan_generator.py`에 헬퍼 추가 (`_prepare_plan_days` 정의 아래, `_normalize_goal_tag` 위 등 모듈 함수 영역):

```python
def _clamp_to_deadline(
    plan: list[PlanDay], *, deadline: date | None
) -> list[PlanDay]:
    """deadline 이후 날짜의 PlanDay 를 제거한다 (P1: 마감 이후 군더더기 차단).

    deadline 이 None 이면 원본을 그대로 돌려준다(기존 거동 보존).
    빈 날짜는 만들지 않는다(통째 제거).
    """
    if deadline is None:
        return plan
    return [day for day in plan if day.get("date") is None or day["date"] <= deadline]
```

그리고 `plan_generator_node` 안에서 `tagged_plan = _prepare_plan_days(...)` 직후에 clamp 를 끼운다:

```python
    tagged_plan = _prepare_plan_days(plan, parsed_goal=parsed_goal, today=today)
    tagged_plan = _clamp_to_deadline(tagged_plan, deadline=parsed_goal.get("deadline"))
```

(파일 상단 import 에 `date` 가 이미 있음: `from datetime import date, timedelta`.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/agents/todo_creation/planner/nodes/test_plan_generator.py::test_drops_tasks_after_deadline tests/agents/todo_creation/planner/nodes/test_plan_generator.py::test_keeps_all_tasks_when_no_deadline -v`
Expected: PASS (2 passed).

- [ ] **Step 5: 기존 테스트 회귀 없음 확인**

Run: `uv run pytest tests/agents/todo_creation/planner/nodes/test_plan_generator.py -v`
Expected: 기존 8개 + 신규 2개 모두 PASS.

- [ ] **Step 6: 커밋**

```bash
git add agents/todo_creation/planner/nodes/plan_generator.py tests/agents/todo_creation/planner/nodes/test_plan_generator.py
git commit -m "fix: plan_generator 마감일 이후 task 제거 (P1 deadline clamp)"
```

---

## Task 2: 프롬프트에 마감-앵커·상대-배치 지시 추가

**Files:**
- Modify: `adapters/todo_creation/_prompts.py`

clamp 는 마감 이후를 막지만, "시험을 마지막 날에 두고 리듬 있게 배치"하는 **품질**은 프롬프트가 담당한다(설계서 §9 Phase 0). 단위 테스트 대상이 아니라 프롬프트 텍스트 변경이다.

- [ ] **Step 1: 대상 프롬프트 찾기**

Run: `grep -n "def \|마감\|deadline\|일자\|계획" adapters/todo_creation/_prompts.py`
`generate_plan` 이 사용하는 plan 생성 system prompt 문자열을 찾는다(일자별 플랜을 만들라고 지시하는 부분).

- [ ] **Step 2: 지시 문구 추가**

찾은 plan 생성 프롬프트의 규칙 나열 부분에 아래 한국어 지시를 **추가**한다(기존 문구는 유지, surgical):

```
- 마감일(시험일 등)이 있으면, 그 날짜를 플랜의 마지막 날로 두고 마감 당일에 핵심 일정(예: "시험 응시")을 배치한다.
- 마감일 이후에는 어떤 task 도 만들지 않는다(회고·정리 등 포함).
- 날짜를 기계적으로 균등 분배하지 말고, 흐름에 맞게 배치한다(예: 개념 학습을 앞쪽에, 최종 점검을 마감 직전에).
```

- [ ] **Step 3: 프롬프트 빌더 단위 테스트가 있으면 갱신, 없으면 스모크 확인**

Run: `grep -rln "_prompts" tests/ || echo "no prompt tests"`
프롬프트 텍스트를 검증하는 테스트가 있으면 위 문구 포함을 단언하는 assert 를 추가한다. 없으면 다음 명령으로 문구가 들어갔는지만 확인:

Run: `grep -n "마감일 이후에는 어떤 task" adapters/todo_creation/_prompts.py`
Expected: 1개 매치.

- [ ] **Step 4: 커밋**

```bash
git add adapters/todo_creation/_prompts.py
git commit -m "feat: plan 프롬프트에 마감-앵커·상대-배치 지시 추가 (P1)"
```

---

## Task 3: P1 회귀 테스트 (설계서 성공기준 3b)

**Files:**
- Test: `tests/agents/todo_creation/planner/nodes/test_plan_generator.py`

clamp(Task 1)와 별개로, "마감 당일 이후 0개" 라는 P1 핵심 불변을 **명시적 회귀 테스트**로 못 박는다.

- [ ] **Step 1: 회귀 테스트 작성**

같은 테스트 파일에 추가:

```python
async def test_p1_no_task_strictly_after_deadline() -> None:
    """P1 회귀: 마감일 '이후'(>)에는 어떤 task 도 남지 않는다."""
    deadline = _TODAY + timedelta(days=6)  # "일주일 뒤" 류
    plan: list[PlanDay] = [
        {"date": _TODAY + timedelta(days=5), "tasks": [TaskCandidate(title="최종점검", due_date=_TODAY + timedelta(days=5))]},
        {"date": _TODAY + timedelta(days=6), "tasks": [TaskCandidate(title="시험 응시", due_date=_TODAY + timedelta(days=6))]},
        {"date": _TODAY + timedelta(days=7), "tasks": [TaskCandidate(title="회고", due_date=_TODAY + timedelta(days=7))]},
    ]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(
        _state({"goal_tag": "정처기", "deadline": deadline}), _config(llm)
    )

    all_tasks = result["todos"] + result["calendar_events"]
    assert all(t.due_date <= deadline for t in all_tasks)
    assert any(t.title == "시험 응시" and t.due_date == deadline for t in all_tasks)
    assert all(t.title != "회고" for t in all_tasks)
```

- [ ] **Step 2: 테스트 실행 (Task 1 구현 후이므로 통과해야 함)**

Run: `uv run pytest tests/agents/todo_creation/planner/nodes/test_plan_generator.py::test_p1_no_task_strictly_after_deadline -v`
Expected: PASS. (만약 FAIL 이면 Task 1 clamp 가 `<= deadline` 경계를 올바로 처리하는지 확인.)

- [ ] **Step 3: 커밋**

```bash
git add tests/agents/todo_creation/planner/nodes/test_plan_generator.py
git commit -m "test: P1 회귀 — 마감일 이후 task 없음 보장"
```

---

## Task 4: SFT측 horizon 규칙 확인 + Phase 0 전체 검증

**Files:**
- Verify only: `sft_pipeline/build/plan_schemas.py` (`check_plan_consistency`)

설계서 §3.5는 deadline 규칙을 "학습·런타임 공통"이라 한다. SFT측은 이미 `check_plan_consistency`에 `due_date > horizon` 금지가 있다(`plan_schemas.py` 의 `_task_errors`). Phase 0에서는 **코드 추가 없이 동작 확인**만 한다(런타임과 규칙이 일치함을 문서화).

- [ ] **Step 1: SFT측 horizon 금지 규칙 확인**

Run: `grep -n "horizon" sft_pipeline/build/plan_schemas.py`
Expected: `due_date가 horizon(D-...) 초과` 위반 메시지가 존재. (이미 런타임 clamp 와 동일 취지 — 마감/지평선 이후 금지.)

- [ ] **Step 2: 관련 SFT 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_plan_schemas.py -v`
Expected: PASS (horizon 초과 케이스 포함).

- [ ] **Step 3: Phase 0 전체 스위트 그린 확인**

Run: `uv run pytest tests/agents/todo_creation/planner/ -q`
Expected: 전체 PASS (clamp·회귀 포함).

- [ ] **Step 4: 마무리 커밋(필요 시) + Phase 0 종료**

Phase 0는 독립 머지 가능(설계서 §9). 코드 변경이 없으면 커밋 생략. 변경이 있었다면:

```bash
git add -A && git commit -m "chore: Phase 0 검증 — 런타임/SFT 마감 규칙 일치 확인"
```

---

## Phase 0 완료 기준 (Definition of Done)

- [ ] `_clamp_to_deadline` 로 마감일 이후 task 가 런타임에서 제거됨 (Task 1).
- [ ] plan 프롬프트가 마감-앵커·상대-배치를 지시함 (Task 2).
- [ ] P1 회귀 테스트가 "마감 이후 0개 + 마감일에 핵심 일정"을 보장 (Task 3).
- [ ] 런타임 clamp ↔ SFT horizon 규칙이 같은 취지임을 확인 (Task 4).
- [ ] `tests/agents/todo_creation/planner/` 전체 그린.

---

## Phase 1 로드맵 (별도 플랜으로 전개 예정 — 아래는 task 목록, 전체 코드 아님)

> ⚠️ Phase 1은 Phase 0가 머지된 뒤 **자체 full 플랜**(`docs/superpowers/plans/…-phase1.md`)으로 bite-sized 전개한다. 아래는 범위 고정용 task 목록이다.

스키마 뱅크 + 내용 부담 적은 종류(routine/vague_goal):
1. `planner/slot_schemas.py` 신규 — `SLOT_SCHEMAS` 레지스트리(exam/routine/vague_goal/lifestyle 필수·선택 슬롯, 질문 템플릿, 우선순위). 설계서 §3.2 표 그대로.
2. `state.py` `ParsedGoal` 에 `plan_kind` + 일상 슬롯 필드 추가.
3. `judge_sufficiency` 를 스키마 구동으로 — plan_kind 분류 + 필수 슬롯 충족 판정. 기존 `goal_rules.py` exam 휴리스틱을 exam 스키마 엔트리로 흡수.
4. follow_up ≤2턴 캡 유지/일반화(D9), 스키마별 override.
5. `allocator.py` 신규 기본형 — 용량 선계산 + 상대→절대 매핑 + clamp(Phase 0 규칙 승계) + routine cadence horizon 전개.
6. **enrichment 일괄 삭제**(D7): 노드·Tavily 어댑터·port 와이어링·테스트.
7. 각 단계 TDD + `judge_sufficiency` 분류 테스트(설계서 성공기준 1·2·3).

**의존성:** Phase 0의 clamp 규칙을 allocator 가 승계.

---

## Phase 2 로드맵 (별도 플랜으로 전개 예정)

> ⚠️ Phase 1 머지 후 자체 full 플랜으로 전개.

뉴로-심볼릭 완성 + lifestyle 라이브러리 + SFT:
1. `plan_generator` 분업 완성 — LLM(N개 task목록+상대배치 rel_day) → 코드(매핑+clamp) → critic 루프. SFT 타깃을 task목록+상대배치로 전환(§4.3).
2. `planner/content_library.yaml` 신규(D10) + lifestyle/vague_goal 라이브러리 검색·선택+개인화 경로(§3.7).
3. 런타임 critic = `check_plan_consistency` 미러를 런타임에 반영(용량 규칙 포함, §3.5). 초과 시 유연=축소 / 고정=사용자 통지.
4. SFT: `build_daily_followup_sft.py`(멀티턴) + allocator 골든셋 + `validate_daily_sft.py`(2층 검증, §4.4·§4.5).
5. lifestyle 내용 eval(성공기준 3d) + 우겨넣기 방지 테스트(3e) + 미러 동기화 테스트(5).

**의존성:** Phase 1의 스키마 뱅크·allocator.

---

## Self-Review (작성자 체크)

- **스펙 커버리지:** Phase 0는 설계서 §9 Phase 0 + §3.5 deadline 규칙 + 성공기준 3b를 커버. P1(증상표) 해결. Phase 1/2 항목은 로드맵으로 매핑(각자 별도 플랜).
- **플레이스홀더:** Phase 0 task 들은 실제 코드·명령·기대출력 포함. Phase 1/2는 "로드맵(별도 플랜)"으로 명시적으로 분리 — task 내 위장 플레이스홀더 아님.
- **타입 일관성:** `_clamp_to_deadline(plan, *, deadline)` 시그니처가 Task 1·3에서 동일. `PlanDay`/`TaskCandidate`/`ParsedGoal` 는 기존 코드 타입 그대로 사용.
