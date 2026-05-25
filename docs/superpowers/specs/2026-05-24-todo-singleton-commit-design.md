# TODO 자동 생성 — 싱글턴 + COMMIT 파이프라인 설계 (LangGraph)

**작성일:** 2026-05-24
**범위:** `docs/features/todo/architecture.mmd` 의 **SINGLE** 서브그래프 + **COMMIT** 서브그래프 + **퀘스트 트리거 게이트**. 멀티턴은 후속 스펙.
**관련 문서:**

- 피처 사양: [../../features/todo/CLAUDE.md](../../features/todo/CLAUDE.md)
- 아키텍처 다이어그램: [../../features/todo/architecture.mmd](../../features/todo/architecture.mmd)
- 공통 AI 규칙: [../../AI_RULES.md](../../AI_RULES.md)
- 데이터 모델: [../../DATA_MODEL.md](../../DATA_MODEL.md) — §3 (TODO/일정/퀘스트)
- 참고 구현 패턴: `agents/character_creation/` (LangGraph + Ports + 비동기)

---

## 0. 결정 요약 (Brainstorm Outcomes)

| #   | 결정                                                                                                       | 근거                                                                      |
| --- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| D1  | **두 개의 컴파일된 LangGraph** (`generate_graph`, `commit_graph`). interrupt/checkpointer 없음.            | 클라이언트가 후보 상태 보유 (버튼 확정·수정 후 재전송).                   |
| D2  | **퀘스트 트리거를 commit_graph 내부 노드**로 포함 (`quest_gate` conditional edge + `quest_dispatch` 노드). | 그래프 추적·재시도·로깅 일관성. character_creation의 cleanup 패턴과 동일. |
| D3  | **Ports + 실제 LLM 어댑터만**. DB/Redis는 in-memory 페이크.                                                | 멀티턴·실제 백엔드는 다음 스펙. 본 스펙은 파이프라인 구조에 집중.         |
| D4  | **멱등성 키 필수** (`commit_graph`의 `CommitInput.idempotency_key`). 클라가 발급.                          | 확정 버튼 중복 클릭·재시도 안전.                                          |
| D5  | **C3 자동 재분류** — 사용자가 수정해서 보낸 commit payload는 `due_date` 기준으로 백엔드가 재분류.          | 클라이언트 UX 유연성.                                                     |
| D6  | **B5 — 과거 due_date는 silent `today` 보정 + 로깅**. 4xx 던지지 않음.                                      | LLM 작은 실수 흡수. 빈도 낮고 사용자 의도 추정 가능.                      |
| D7  | **task_splitter 상한 — 21개 이상이면 `LLMOutputError`**. truncate 안 함.                                   | 정상 입력 시 도달 불가능한 수치. 초과는 LLM 오작동 신호.                  |
| D8  | **싱글턴 path의 `tags`는 항상 `[]`**. Tagger는 멀티턴 도입 시점에.                                         | 본 스펙 범위 축소.                                                        |
| D9  | **`time_hint`는 schema에 보관만**. 캘린더 이벤트 시작 시각 변환 안 함.                                     | open question §7.4 — 후속 스펙.                                           |
| D10 | **퀘스트 카운트 키 = `quest_distribute:{user_id}:{YYYY-MM-DD KST}`**. 리셋 = 서버 KST 자정.                | open question §7.7 결정.                                                  |
| D11 | **Rate limit은 본 스펙 밖** (미들웨어/API 게이트웨이 책임).                                                | 파이프라인 관심사 분리.                                                   |
| D12 | **HTTP 응답 매핑은 호출자 책임**. 본 스펙은 예외 raise까지만 책임.                                         | character_creation 동일 패턴.                                             |

---

## 1. 디렉토리 레이아웃

```
agents/todo_creation/
├── __init__.py
├── single_turn/
│   ├── __init__.py
│   ├── pipeline.py            # run(input, *, ports, now) -> GenerateResult
│   ├── graph.py               # build_generate_graph()
│   ├── state.py               # GenerateGraphState (TypedDict)
│   └── nodes/
│       ├── __init__.py
│       ├── validate.py
│       ├── task_splitter.py
│       └── date_router.py
├── commit/
│   ├── __init__.py
│   ├── pipeline.py            # run(input, *, ports, now) -> CommitResult
│   ├── graph.py               # build_commit_graph()
│   ├── state.py               # CommitGraphState (TypedDict)
│   └── nodes/
│       ├── __init__.py
│       ├── validate.py
│       ├── save_dispatcher.py
│       ├── quest_gate.py      # conditional edge 함수
│       └── quest_dispatch.py
├── schemas.py                 # 외부 I/O Pydantic 모델
├── protocols.py               # LLMPort, TodoRepositoryPort, QuestCounterPort, QuestDispatchPort
├── debug.py                   # log_start / log_step / log_end (character_creation 패턴 복사)
└── exceptions.py

adapters/todo_creation/
├── __init__.py
├── _prompts.py                # task_splitter system/user 프롬프트
├── openai_llm.py              # 실제 LLM 어댑터 (유일한 실제 백엔드)
├── fake_llm.py                # scripted 응답 (테스트·streamlit)
├── memory_repo.py             # 가짜 TODO/Calendar DB (dict + asyncio.Lock)
└── memory_quest_counter.py    # 가짜 Redis (dict + asyncio.Lock, atomic incr_if_under_limit)

tests/agents/todo_creation/
├── __init__.py
├── conftest.py
├── test_schemas.py
├── single_turn/
│   ├── nodes/
│   │   ├── test_validate.py
│   │   ├── test_task_splitter.py
│   │   └── test_date_router.py
│   └── test_pipeline.py
└── commit/
    ├── nodes/
    │   ├── test_validate.py
    │   ├── test_save_dispatcher.py
    │   ├── test_quest_gate.py
    │   └── test_quest_dispatch.py
    └── test_pipeline.py

tests/adapters/todo_creation/
├── test_openai_llm.py             # 모킹 단위
├── test_openai_llm_contract.py    # @pytest.mark.contract (CI 게이트, default skip)
├── test_memory_repo.py
└── test_memory_quest_counter.py
```

---

## 2. 그래프 구조

### 2.1 `generate_graph` — 후보 생성

```
START → validate ──pass──→ task_splitter ─→ date_router → END
              └──fail──→ END (state.error set)
```

- `validate`: 4xx 즉시. LLM 미호출.
- `task_splitter`: `RetryPolicy(max_attempts=3, retry_on=(LLMFailedError,))`. JSON 파싱 실패는 노드 내부에서 1회만 재호출 후 `LLMOutputError` raise.
- `date_router`: 순수 로직 (`due_date == today` → todos / `> today` → events).

### 2.2 `commit_graph` — 저장 + 퀘스트 트리거

```
START → validate ─→ save_dispatcher ─┬─(당일 TODO≥1 AND 멱등 miss AND counter<5)─→ quest_dispatch ─→ END
                                     └─(그 외)──────────────────────────────────────────────────→ END
```

- `validate`: C1/C2/C4/C5 위반 → 4xx. C3는 자동 재분류 후 통과.
- `save_dispatcher`: `find_by_idempotency_key` 선조회 → hit이면 기존 결과 로드(save 스킵), miss면 단일 트랜잭션 저장.
- `quest_gate`: `add_conditional_edges`의 라우터 함수. 위 조건 모두 만족 시 `quest_dispatch`로, 아니면 `END`로.
- `quest_dispatch`: `QuestDispatchPort.dispatch` 호출. 실패해도 silent skip, log, `state.quest_triggered=False`, END로 통과.

### 2.3 그래프 컴파일 위치

`generate_graph`, `commit_graph` 각각 모듈 최상위에서 `_GRAPH = build_*_graph()` 로 한 번만 컴파일 (character_creation 패턴).

---

## 3. 스키마 / 상태 / 포트

### 3.1 외부 I/O (`schemas.py`)

```python
class SingleTurnInput(BaseModel):
    user_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1, max_length=200)
    today: date

class TaskCandidate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    due_date: date
    time_hint: str | None = None    # 보관만, 캘린더 시작 시각 변환 안 함 (D9)
    tags: list[str] = []            # 싱글턴에서는 항상 [] (D8)

class GenerateResult(BaseModel):
    todos: list[TaskCandidate]            # due_date == today
    calendar_events: list[TaskCandidate]  # due_date > today

class CommitInput(BaseModel):
    user_id: str = Field(min_length=1)
    idempotency_key: UUID
    today: date
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]

    @model_validator(mode="after")
    def _check_total_size(self):
        if len(self.todos) + len(self.calendar_events) > 50:
            raise ValueError("too many items")
        if len(self.todos) + len(self.calendar_events) == 0:
            raise ValueError("empty payload")
        return self

class CommitResult(BaseModel):
    todo_ids: list[UUID]
    event_ids: list[UUID]
    quest_distribution_triggered: bool
```

### 3.2 그래프 상태 (`state.py`)

```python
# single_turn/state.py
class GenerateGraphState(TypedDict, total=False):
    # required
    input: SingleTurnInput
    now: datetime
    # produced
    split_tasks: list[TaskCandidate] | None
    result: GenerateResult | None
    error: Exception | None

# commit/state.py
class CommitGraphState(TypedDict, total=False):
    # required
    input: CommitInput
    now: datetime
    # produced
    re_routed_todos: list[TaskCandidate] | None
    re_routed_events: list[TaskCandidate] | None
    idempotent_hit: bool | None
    todo_ids: list[UUID] | None
    event_ids: list[UUID] | None
    quest_triggered: bool | None
    error: Exception | None
```

### 3.3 포트 (`protocols.py`)

```python
class LLMPort(Protocol):
    async def split_tasks(
        self, *, prompt: str, today: date
    ) -> list[TaskCandidate]: ...

class TodoRepositoryPort(Protocol):
    async def find_by_idempotency_key(
        self, *, user_id: str, key: UUID
    ) -> CommitResult | None: ...

    async def save(
        self,
        *,
        user_id: str,
        idempotency_key: UUID,
        todos: list[TaskCandidate],
        events: list[TaskCandidate],
    ) -> tuple[list[UUID], list[UUID]]: ...  # 한 트랜잭션

class QuestCounterPort(Protocol):
    async def incr_if_under_limit(
        self, *, user_id: str, day_kst: date, limit: int
    ) -> bool: ...  # True면 증가 성공(분배 가능), False면 한도 초과

class QuestDispatchPort(Protocol):
    async def dispatch(self, *, user_id: str) -> None: ...
```

### 3.4 Ports 묶음

```python
# single_turn/pipeline.py
@dataclass
class GeneratePorts:
    llm: LLMPort

# commit/pipeline.py
@dataclass
class CommitPorts:
    repository: TodoRepositoryPort
    quest_counter: QuestCounterPort
    quest_dispatch: QuestDispatchPort
```

`config["configurable"]["ports"]`로 그래프에 주입. `now: datetime`도 동일하게 `config["configurable"]["now"]`로 주입 (테스트 시각 고정).

---

## 4. 데이터 흐름

### 4.1 generate_graph

```
POST /todos/generate { user_id, prompt, today }
  ↓
generate_pipeline.run(input, ports, now)
  ↓ initial state: {input, now}
  ↓
validate
  ↓ pass
task_splitter   (LLMPort.split_tasks)
  ├ B5: due_date<today → today 보정 + 로그
  ├ B6: title 81자+ → 80자 truncate
  ↓ state.split_tasks
date_router      (순수 로직)
  ↓ state.result
END
  ↓
200 OK: GenerateResult
```

### 4.2 클라이언트 ↔ 사용자 (백엔드 비관여)

- 사용자 액션: 그대로 확정 / 항목 수정 / 일부 삭제
- 클라가 보유: 후보 목록 + `idempotency_key = uuid4()` (확정 버튼 누르는 시점 1회 발급, 재시도 시 동일)

### 4.3 commit_graph

```
POST /todos/commit { user_id, idempotency_key, today, todos, calendar_events }
  ↓
commit_pipeline.run(input, ports, now)
  ↓
validate
  ├ C1/C2/C4/C5 위반 → 4xx
  ├ C3: due_date 기준 자동 재분류 → state.re_routed_*
  ↓
save_dispatcher
  ├ find_by_idempotency_key
  │   ├ hit  → state.idempotent_hit=True, todo_ids/event_ids 기존값
  │   └ miss → save() (단일 트랜잭션), state.idempotent_hit=False
  ↓
[conditional: quest_gate]
  ├ 당일 TODO ≥1 AND state.idempotent_hit==False AND counter.incr<5 → quest_dispatch
  └ 그 외 → END (quest_triggered=False)
  ↓
quest_dispatch (선택 경로만)
  ├ port.dispatch() 성공 → quest_triggered=True
  └ 예외 발생 → silent skip + log, quest_triggered=False
  ↓
END
  ↓
200 OK: CommitResult
```

### 4.4 핵심 보장 (Invariants)

| #   | 보장                                                | 메커니즘                                                     |
| --- | --------------------------------------------------- | ------------------------------------------------------------ |
| I1  | TODO + Calendar는 함께 저장되거나 함께 실패         | `TodoRepositoryPort.save` 단일 트랜잭션                      |
| I2  | 같은 `idempotency_key` 재요청 시 중복 저장 0        | `find_by_idempotency_key` 선조회 + DB unique 제약            |
| I3  | 멱등 hit 시 퀘스트 트리거 재호출 0                  | `quest_gate` 조건에 `idempotent_hit==False` 포함             |
| I4  | 퀘스트 카운터 race-safe                             | `incr_if_under_limit` atomic (Redis INCR/Lua, 페이크는 lock) |
| I5  | 퀘스트 분배 실패가 commit 응답을 깨뜨리지 않음      | `quest_dispatch` 노드가 예외 흡수, log, END 통과             |
| I6  | 시각 의존 로직(today 보정, KST 자정 키) 테스트 가능 | `now: datetime`을 `config`로 주입                            |

---

## 5. 에러 처리

### 5.1 예외 계층 (`exceptions.py`)

```python
class TodoCreationError(Exception): ...

# 4xx
class ValidationError(TodoCreationError): ...        # A1–A4, C1/C2/C5
class AuthorizationError(TodoCreationError): ...     # C4

# 5xx
class LLMFailedError(TodoCreationError): ...         # 네트워크/타임아웃/인증
class LLMOutputError(TodoCreationError): ...         # B1/B2/B3/B4 — 재시도 후에도 실패
class SaveFailedError(TodoCreationError): ...        # D1 — 트랜잭션 롤백
```

`quest_dispatch`의 내부 예외는 `TodoCreationError` 하위로 분류하지 않고 노드 안에서 흡수 (silent skip).

### 5.2 노드별 정책

| 노드                        | 재시도                                                     | 보상/롤백          | 종착 예외                                |
| --------------------------- | ---------------------------------------------------------- | ------------------ | ---------------------------------------- |
| `single_turn/validate`      | 없음                                                       | —                  | `ValidationError`                        |
| `single_turn/task_splitter` | `RetryPolicy(3, LLMFailedError)` + 노드 내 파싱 1회 재호출 | —                  | `LLMFailedError` / `LLMOutputError`      |
| `single_turn/date_router`   | —                                                          | —                  | —                                        |
| `commit/validate`           | 없음                                                       | —                  | `ValidationError` / `AuthorizationError` |
| `commit/save_dispatcher`    | 없음 (재시도는 어댑터 결정)                                | 트랜잭션 자동 롤백 | `SaveFailedError`                        |
| `commit/quest_dispatch`     | 없음                                                       | 없음               | (raise 안 함, 흡수)                      |

### 5.3 END(error) 전수 (generate_graph)

| 단계          | 트리거                         | 코드 | HTTP |
| ------------- | ------------------------------ | ---- | ---- |
| validate      | prompt > 200자                 | A1   | 4xx  |
| validate      | prompt 빈 입력 / 공백만        | A2   | 4xx  |
| validate      | user_id 누락/형식 오류         | A3   | 4xx  |
| validate      | today 형식 오류                | A4   | 4xx  |
| task_splitter | LLM 호출 3회 연속 실패         | —    | 5xx  |
| task_splitter | JSON 파싱 2회 실패             | B1   | 5xx  |
| task_splitter | 빈 task 배열 재생성 실패       | B2   | 5xx  |
| task_splitter | task 수 > 20                   | B3   | 5xx  |
| task_splitter | due_date 형식 오류 재시도 실패 | B4   | 5xx  |

**과거 날짜(B5)는 에러 아님** — silent `today` 보정 후 정상 흐름.

### 5.4 멱등성 부분 실패

| 시나리오                        | 결과                                    | 재시도 처리                                                                                        |
| ------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------- |
| save 성공 → quest_dispatch 실패 | DB 저장됨, `triggered=False`            | 같은 key 재호출 → hit, save 스킵, `idempotent_hit=True` 라서 quest_gate가 `quest_dispatch`로 안 감 |
| save 도중 DB 실패               | 트랜잭션 롤백 (idempotency 레코드 포함) | 같은 key 재호출 → miss → 정상 재실행                                                               |

퀘스트 분배 별도 백오프 큐는 본 스펙 밖. `quest_dispatch` 노드에 TODO 주석으로만 명시.

### 5.5 HTTP 응답 매핑 (호출자 책임)

| 예외                 | HTTP | body                                   |
| -------------------- | ---- | -------------------------------------- |
| `ValidationError`    | 400  | `{error: "validation", detail: "..."}` |
| `AuthorizationError` | 403  | `{error: "forbidden"}`                 |
| `LLMFailedError`     | 503  | `{error: "llm_unavailable"}`           |
| `LLMOutputError`     | 502  | `{error: "llm_bad_output"}`            |
| `SaveFailedError`    | 500  | `{error: "save_failed"}`               |

본 스펙은 예외 raise까지만 책임. FastAPI/라우터가 매핑.

### 5.6 로깅 (`debug.py`)

`log_start(input, kind)` / `log_step(step, node, update)` / `log_end(final)` — character_creation `debug.py`와 동일 시그니처. `pipeline.run`에서 `astream(stream_mode=["updates", "values"])` 받아서 노드별 업데이트마다 호출. PII 로깅 정책은 `docs/AI_RULES.md` 준수.

---

## 6. 테스트 전략

전역 룰: pyproject `--cov-fail-under=80`. cov 대상 = `agents/` (어댑터는 모킹 단위 테스트만).

### 6.1 단위 테스트 — 노드별

| 노드                        | 케이스                                                                                                                                                                                                                |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `single_turn/validate`      | 정상 / 길이 200·201자 경계 / 빈 / 공백만 / user_id 누락 / today 형식 오류                                                                                                                                             |
| `single_turn/task_splitter` | 정상 split / 파싱 1회 실패→성공 / 파싱 2회 실패→`LLMOutputError` / 빈 배열 재생성→5xx / task 21개→`LLMOutputError` / due_date<today→today 보정+로그 / title 81자→80자 truncate / LLM 호출 예외→`LLMFailedError` raise |
| `single_turn/date_router`   | 전부 today / 전부 future / 혼합 / 빈 입력                                                                                                                                                                             |
| `commit/validate`           | C1 빈 배열 / C2 형식 / C3 잘못 분류 → 자동 재분류 통과 / C4 user_id 불일치 / C5 합계 51개                                                                                                                             |
| `commit/save_dispatcher`    | 멱등 miss → 신규 저장 / 멱등 hit → 기존 결과, save 호출 0 / save 예외 → `SaveFailedError`                                                                                                                             |
| `commit/quest_gate`         | 당일 0 → END / 당일 ≥1 + hit → END / 당일 ≥1 + miss + counter False → END / 당일 ≥1 + miss + counter True → quest_dispatch                                                                                            |
| `commit/quest_dispatch`     | 정상 → `triggered=True` / 포트 예외 → `triggered=False`, raise 안 됨, 로그                                                                                                                                            |

각 노드는 순수 함수 (state → state diff). LangGraph 컴파일 불필요.

### 6.2 통합 테스트 — 그래프 단위

`build_generate_graph()` / `build_commit_graph()` 컴파일 후 `.ainvoke` 또는 `.astream` 호출. 페이크 ports + 고정 `now`.

**generate_graph**

| 시나리오                                          | 기대                             |
| ------------------------------------------------- | -------------------------------- |
| Happy: 오늘 only                                  | todos=1, events=0                |
| Happy: 오늘+미래 혼합                             | todos=1, events=1                |
| Happy: 과거 자동 보정                             | todos=1 (today로 보정), events=0 |
| 입력 거부 (prompt 201자)                          | `ValidationError` raise          |
| LLM 재시도 후 성공 (페이크 2회 실패 → 3회째 성공) | 정상 결과                        |
| LLM 완전 실패 (페이크 3회 실패)                   | `LLMFailedError` raise           |

**commit_graph**

| 시나리오                        | 기대                                                        |
| ------------------------------- | ----------------------------------------------------------- |
| Happy: 당일 TODO + quota 남음   | 저장 + `triggered=True`, counter +1                         |
| Happy: 당일 TODO + quota 5/5    | 저장 + `triggered=False`, counter 그대로                    |
| Happy: future events만 (당일 0) | 저장 + `triggered=False`, counter 그대로                    |
| 멱등성: 같은 key 두 번 호출     | 두 번째 hit, save 호출 1회, 두 번째 trigger 없음, 응답 동일 |
| C3 자동 재분류                  | today 항목이 events에 들어와도 재분류 후 저장               |
| save 실패                       | `SaveFailedError`, DB 변경 0, counter 변경 0                |
| quest_dispatch 실패             | 저장 성공, `triggered=False`, 로그                          |

### 6.3 계약 테스트 — 실제 LLM 어댑터

- **단위 (모킹)**: OpenAI SDK 호출 `pytest-mock`으로 모킹. 프롬프트에 today 포함 / structured output 옵션 활성 / 반환 `TaskCandidate` 파싱 검증.
- **계약 (@pytest.mark.contract)**: `OPENAI_API_KEY` 있으면 실제 API 1회. 기본 skip. "오늘 코테 1개, 3일 뒤 발표" → task 2개 / due_date 분기 확인.

### 6.4 페이크 어댑터 (`adapters/todo_creation/`)

- `fake_llm.py`: scripted 응답 큐. 실패 시뮬레이션 옵션 (n회 실패 후 성공 / 항상 실패).
- `memory_repo.py`: dict + `asyncio.Lock`. idempotency_key 기반 dedup, save는 atomic.
- `memory_quest_counter.py`: dict + `asyncio.Lock`. `incr_if_under_limit`는 lock 안에서 검사·증가.

---

## 7. 마이그레이션·롤아웃 노트

- 본 스펙 산출물 머지 시점에는 라우터(FastAPI 등) 미연결. 후속 스펙에서 라우터·실제 DB 어댑터·실제 Redis·실제 퀘스트 분배 에이전트 연결.
- streamlit 데모 앱(`streamlit_app/`)에 싱글턴 generate→commit 흐름 추가는 본 스펙의 stretch goal. 기본은 페이크 어댑터 + pytest로 검증.
- `CHANGELOG.md`에 본 파이프라인 추가 항목 기록 (DoD: `docs/FEATURES.md` §4).
- `docs/features/todo/architecture.mmd`는 as-built 갱신 — 본 스펙이 SINGLE+COMMIT만 다루므로 MULTI 부분은 그대로 유지.

---

## 8. 본 스펙에서 의도적으로 배제한 항목

| 항목                                | 사유                                   | 후속                                    |
| ----------------------------------- | -------------------------------------- | --------------------------------------- |
| 멀티턴 (MULTI 서브그래프)           | 별도 스펙                              | TODO doc §4.5–§4.10 그대로 차용         |
| 실제 DB 어댑터 (Postgres/등)        | 페이크로 충분                          | 후속 스펙에서 마이그레이션 + 리포지토리 |
| 실제 Redis 어댑터                   | 동일                                   |                                         |
| 실제 퀘스트 분배 에이전트 본체      | `docs/features/quest_generation/` 범위 |                                         |
| 태그 부여 (Tagger)                  | 멀티턴 도입 시점                       | D8                                      |
| `time_hint` → 캘린더 시작 시각 변환 | open question §7.4                     | D9                                      |
| Rate limit                          | 미들웨어 책임                          | D11                                     |
| HTTP 응답 매핑                      | 호출자 책임                            | D12                                     |
| 멀티턴 한국어 검증                  | 멀티턴 스펙                            | open question §7.6                      |
| 퀘스트 분배 백오프 큐               | 실제 백엔드 도입 시점                  | §5.4                                    |

---

## 9. DoD (Definition of Done)

- [ ] `agents/todo_creation/` 위 디렉토리 레이아웃대로 생성, 모든 모듈 import 가능
- [ ] `adapters/todo_creation/` 페이크 + OpenAI 어댑터 구현
- [ ] `pytest --cov` 결과 80%+ (agents/ 기준), 모든 6.1·6.2 시나리오 통과
- [ ] OpenAI 어댑터 모킹 단위 테스트 통과. 계약 테스트는 `OPENAI_API_KEY` 없으면 skip
- [ ] `CHANGELOG.md`에 항목 추가
- [ ] `docs/features/todo/architecture.mmd`는 본 스펙 범위 변경 없음 (검증만)
