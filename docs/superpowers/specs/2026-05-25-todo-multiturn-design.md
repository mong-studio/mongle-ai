# TODO 자동 생성 — 멀티턴 도입 + single/multi 통합 generate_graph 설계 (LangGraph)

**작성일:** 2026-05-25
**범위:** `agents/todo_creation/` 의 single 모드와 multi 모드를 단일 `generate_graph` 로 통합. multi 모드는 `checkpointer + interrupt(follow_up)` 패턴. `commit_graph` 는 기존(2026-05-24 스펙) 그대로 분리 유지.

> **본 spec 은 동일 파일명의 이전 안(multi-only 자체 완결 모듈, `SessionStorePort` + `edit_agent` + `phase_router` + `commit_invoke` 노드 내장)을 사용자 결정에 따라 폐기·대체한다.** 이전 안의 핵심 결정 7건이 어떻게 대체되었는지는 §0.1 의 "Superseded decisions" 표 참조.

**관련 문서:**

- 피처 사양: [../../features/todo/CLAUDE.md](../../features/todo/CLAUDE.md) — §4.5–§4.10 멀티턴 노드 책임
- 직전 단계 스펙 (싱글턴 + commit): [./2026-05-24-todo-singleton-commit-design.md](./2026-05-24-todo-singleton-commit-design.md)
- 후속 후보 분석 (③·④): [./2026-05-25-langgraph-patterns-followup.md](./2026-05-25-langgraph-patterns-followup.md)
- 공통 AI 규칙: [../../AI_RULES.md](../../AI_RULES.md)
- 데이터 모델: [../../DATA_MODEL.md](../../DATA_MODEL.md) — §3 (TODO/일정/퀘스트), §3.4 (tags)
- 참고 구현 패턴: `agents/character_creation/` (Command fan-out, RetryPolicy, ports + 비동기)

---

## 0. 결정 요약 (Brainstorm Outcomes)

| #   | 결정                                                                                                                              | 근거                                                                                                |
| --- | --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| E1  | **단일 `generate_graph`** — single/multi 두 모드를 하나의 컴파일된 그래프에서 처리                                                | 통합 요청. deep-agent 패턴의 의도를 단순 mode-branching graph + interrupt 로 구체화                  |
| E2  | **모드 분기는 명시적 `mode: Literal["single","multi"]` 필드**                                                                     | LLM 라우터/세션 추론보다 결정적이고 테스트 용이. UI 진입점이 이미 두 개                              |
| E3  | **`commit_graph` 는 기존 그대로 분리 유지**                                                                                       | 관심사 분리(LLM 대화 vs DB 트랜잭션), 멱등성 계약 명시성, 장애 격리, 기존 자산 보호                  |
| E4  | **single 은 stateless 1-shot, multi 만 `checkpointer + interrupt(follow_up)`**                                                    | single 은 interrupt 둘 이유 없음(commit 분리). multi 의 follow_up loop 만 thread 보유                |
| E5  | **single_turn/ 노드(`validate`, `task_splitter`, `date_router`) 재사용**, plan 검토 단계 interrupt 제외                            | 회귀 면적 최소화. plan 검토는 클라가 결과를 받아 수정 후 commit 으로 보냄                            |
| E6  | **`session_id` 별도 두지 않고 LangGraph `thread_id` 로 단일화** (multi 만 사용)                                                   | 두 식별자 동시 관리 부담 회피. 첫 multi 호출 시 서버가 발급하여 응답에 포함                          |
| E7  | **`MAX_TURN` 강제 없음**                                                                                                          | 자연 한도(LLM 비용·사용자 이탈)에 위임. 운영 모니터링 책임                                            |
| E8  | **tagger 실패는 silent degrade** (빈 태그, raise 안 함)                                                                            | 태그는 부가 정보. character_creation 의 vlm `None` 패스스루 패턴 차용                                |
| E9  | **history 는 `state["history"]` + checkpointer 에 저장** (별도 SessionStore 미사용)                                                | langgraph checkpointer 가 state 자체를 persist — 추가 인프라 불필요                                  |
| E10 | **`LLMPort` 단일 인터페이스, 5 메서드** (split_tasks + judge_sufficiency + generate_follow_up_question + generate_plan + tag_plan) | character_creation 패턴 동일. 어댑터 1개에 묶음                                                      |
| E11 | **prod checkpointer 어댑터(Postgres/Redis) 본 스펙 밖**, MemorySaver 만 사용                                                       | 인프라 도입 시점에 별도 PR                                                                          |
| E12 | **기존 `single_turn/{pipeline,graph,state}.py` 제거**, 통합 그래프는 `agents/todo_creation/` 최상위에 직배치                       | YAGNI — 별도 `generate/` 디렉토리 신설 안 함                                                         |

### 0.1 Superseded decisions (이전 multi-only spec 대체)

| 이전 결정                                                       | 대체                                                                                         | 사유                                                                                                  |
| --------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `agents/todo_creation/multi_turn/` 자체 pipeline·graph·state    | single+multi 통합 그래프, `multi_turn/` 은 노드 디렉토리만                                    | 통합 요청. 두 진입점 → 한 진입점                                                                       |
| 커스텀 `SessionStorePort` (in-memory → MySQL)                   | langgraph `MemorySaver` checkpointer (state 자체 persist)                                    | 별도 저장소 인프라 결정 회피, langgraph 자체 기능 활용                                                  |
| `commit_invoke` 노드가 multi 그래프 안에서 commit_graph 호출    | commit 호출 분리 — 클라가 GenerateResult 받아 별도 `/todos/commit` 호출                       | 관심사 분리, 장애 격리, 기존 commit_graph 회귀 면적 0                                                  |
| `edit_agent` (LLM tool-calling, `regenerate_plan`/`confirm`)    | plan 검토·수정 단계 그래프에서 제거. 클라가 직접 수정 후 commit                                 | LLM 추가 호출 없이 결정론적 UX. tool-calling 인프라(recursion_limit 등) 회피                            |
| `phase: gathering \| reviewing` + `phase_router` 노드            | phase 모델 없음. follow_up loop 후 plan 생성 즉시 END                                         | 검토 단계가 그래프 밖이 되면서 phase 분리 불필요                                                       |
| `RetryPolicy(max_attempts=2)` (모든 LLM 노드)                   | RetryPolicy(3) (단, follow_up·tagger 는 2). character_creation 과 정합                       | 기존 task_splitter 의 (3) 정책과 통일                                                                  |
| 한국어 비율 ≥0.3, history cap 20                                | 한국어 비율 ≥0.5, history cap 없음                                                            | 휴리스틱은 보수적으로. history cap 은 MAX_TURN 없음과 일관                                              |
| 별도 `MultiTurnLLMPort` + `openai_multi_turn.py`·`fake_multi_turn_llm.py` 어댑터 (이전 spec 부산물로 이미 머지됨) | 단일 `LLMPort` 5 메서드 + 단일 어댑터(`openai_llm.py`·`fake_llm.py`) 로 흡수, 두 multi 전용 어댑터 삭제 | 인터페이스 1개. ISP 보다 일관성·테스트 단순성 우선 (character_creation 패턴). 부산물 어댑터 코드 폐기 surgical 으로 명시 |

---

## 1. 디렉토리 레이아웃

```
agents/todo_creation/
├── __init__.py
├── pipeline.py                  # run(input, *, ports, now, thread_id=None) -> TurnResult
├── graph.py                     # build_generate_graph(checkpointer)
├── state.py                     # GenerateState (single+multi 합집합, total=False)
├── schemas.py                   # GenerateInput Union + TurnResult Union (확장)
├── protocols.py                 # LLMPort 5 메서드 (확장)
├── debug.py                     # log_start / log_step / log_end
├── exceptions.py                # ThreadNotFoundError 추가 (그 외 변경 없음)
├── nodes/
│   ├── __init__.py
│   └── entry.py                 # mode 분기 → Command(goto='single_validate' | 'multi_validate')
├── single_turn/
│   └── nodes/
│       ├── validate.py          # 기존 그대로 (mode='single' 검증)
│       ├── task_splitter.py     # 기존 그대로
│       └── date_router.py       # 기존 그대로 (single + multi 공유 fan-in 노드)
├── multi_turn/
│   ├── __init__.py
│   └── nodes/
│       ├── __init__.py
│       ├── validate.py          # mode='multi' 검증 (≤600자, 한국어 휴리스틱 ≥0.5)
│       ├── planner.py           # sufficiency 판단 → Command(goto='follow_up' | 'plan_generator')
│       ├── follow_up.py         # interrupt(question) — resume 시 history append 후 planner 로
│       ├── plan_generator.py    # 일자별 plan + summary_text (C3 ≤1500자 보장)
│       └── tagger.py            # 태그 부여 후 TaskCandidate 리스트로 normalize (실패 시 빈 태그)
├── commit/                      # 기존 그대로 (변경 없음)
└── middleware/                  # 기존 (trace_callback.py)

adapters/todo_creation/
├── openai_llm.py                # split_tasks 외 4 메서드 흡수 (multi 메서드 통합)
├── fake_llm.py                  # 4 메서드 흡수 (기존 fail_times/responses 큐 패턴 유지)
├── memory_repo.py               # 기존
├── memory_quest_counter.py      # 기존
# 삭제 대상 (이전 multi-only spec 부산물):
# ├── openai_multi_turn.py       # → openai_llm.py 로 흡수
# └── fake_multi_turn_llm.py     # → fake_llm.py 로 흡수

# checkpointer 는 별도 어댑터 없음 — langgraph.checkpoint.memory.MemorySaver 직접 사용

tests/agents/todo_creation/
├── conftest.py
├── test_schemas.py
├── nodes/test_entry.py
├── single_turn/nodes/           # 기존 그대로
├── multi_turn/nodes/
│   ├── test_validate.py
│   ├── test_planner.py
│   ├── test_follow_up.py
│   ├── test_plan_generator.py
│   └── test_tagger.py
├── test_graph.py                # 통합 그래프 단위 (MemorySaver 기반)
├── test_pipeline.py             # pipeline 엔트리
└── commit/                      # 기존 그대로

tests/adapters/todo_creation/
├── test_openai_llm.py           # 5 메서드 모킹 단위 (이전 test_openai_multi_turn.py 케이스 흡수)
├── test_openai_llm_contract.py  # @pytest.mark.contract (기본 skip)
├── test_fake_llm.py             # 기존
├── test_memory_repo.py
└── test_memory_quest_counter.py
# 삭제 대상:
# └── test_openai_multi_turn.py  # → test_openai_llm.py 로 흡수
```

---

## 2. 그래프 구조

### 2.1 generate_graph — 통합 (single + multi)

```
                       START
                         │
                       entry
                         │  Command(goto=...)
              ┌──────────┴──────────┐
       mode=single              mode=multi
              │                     │
       single_validate          multi_validate
              │                     │
       task_splitter            planner ←─────┐
              │                     │ Command │
              │            ┌────────┴────┐    │
              │       follow_up      plan_generator
              │      + interrupt          │
              │            │              │
              │            └─→ planner ───┘ (loop)
              │            (after resume)
              │                          │
              │                       tagger
              │                          │
              └─────────┬────────────────┘
                       │
                  date_router
                       │
                      END
```

- `entry`: `mode` 만 보고 `Command(goto='single_validate' | 'multi_validate')`. mode 누락 → `ValidationError`.
- `single_validate`: 기존 `single_turn/nodes/validate.py` (≤200자, 빈/공백).
- `task_splitter`: 기존 그대로. `RetryPolicy(max_attempts=3, retry_on=(LLMFailedError,))` + 노드 내 파싱 1회 재호출.
- `multi_validate`: ≤600자, 한국어 음절 비율 ≥0.5 (휴리스틱). 빈/공백.
- `planner`: `judge_sufficiency` 호출. `Command(goto='follow_up')` (insufficient) 또는 `Command(goto='plan_generator')` (sufficient). `RetryPolicy(3, LLMFailedError)` + 파싱 1회 재호출.
- `follow_up`: 아래 의사코드. `interrupt()` 호출 후 resume 시 같은 노드가 user_answer 와 함께 재진입. `add_edge("follow_up", "planner")`.
- `plan_generator`: `generate_plan` 호출 → `(summary_text, days)`. C3 위반 시 노드 내부 재생성 1회 → 그래도 위반 시 truncate(1500자) + log.
- `tagger`: `tag_plan` 호출. 실패 시 모든 task `tags=[]` 로 degrade, `log`, raise 안 함.
- `date_router`: 기존 그대로. multi 의 경우 plan 의 모든 days·tasks 를 펼친 리스트로 입력.

### 2.2 follow_up 노드 (의사코드)

```python
async def follow_up_node(state, config):
    ports = config["configurable"]["ports"]
    question = await ports.llm.generate_follow_up_question(
        missing_aspects=state["missing_aspects"],
        history=state["history"],
    )
    user_answer = interrupt(question)   # 일시정지 → resume 시 user_answer 주입
    return {
        "follow_up_question": question,
        "history": state["history"]
            + [{"role": "assistant", "content": question},
               {"role": "user", "content": user_answer}],
    }
```

`pipeline.run` 은 첫 호출과 resume 호출을 다음과 같이 분기:

```python
async def run(input, *, ports, now, thread_id=None):
    config = {"configurable": {"ports": ports, "now": now}}
    if isinstance(input, MultiGenerateInput) and input.thread_id:
        config["configurable"]["thread_id"] = input.thread_id
        result = await _GRAPH.ainvoke(Command(resume=input.message), config=config)
    else:
        new_thread = str(uuid.uuid4())
        config["configurable"]["thread_id"] = new_thread
        initial = _build_initial_state(input, now)
        result = await _GRAPH.ainvoke(initial, config=config)
    return _to_turn_result(result, config["configurable"]["thread_id"])
```

interrupt 발생 시 `_GRAPH.ainvoke` 는 정상 종료 없이 `__interrupt__` 키를 포함한 state 를 반환 — `_to_turn_result` 가 그 경우 `FollowUpResult`, 그 외엔 `GenerateResult` 로 매핑.

### 2.3 commit_graph — 기존(2026-05-24 스펙)

```
START → validate ─→ save_dispatcher ─┬─(당일 TODO≥1 AND 멱등 miss AND counter<5)─→ quest_dispatch → END
                                     └─(그 외)──────────────────────────────────────────────────→ END
```

본 스펙은 commit_graph 코드/테스트를 건드리지 않음.

### 2.4 컴파일 위치

`generate_graph` 는 모듈 최상위에서 한 번 컴파일:

```python
# agents/todo_creation/graph.py
_GRAPH = build_generate_graph(checkpointer=MemorySaver())
```

`build_generate_graph(checkpointer=...)` 는 의존성 주입 가능하도록 — 테스트는 `MemorySaver()` 인스턴스를 명시 전달.

---

## 3. 스키마 / 상태 / 포트

### 3.1 외부 I/O (`schemas.py`)

```python
class SingleGenerateInput(BaseModel):
    mode: Literal["single"] = "single"
    user_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1, max_length=200)
    today: date

class MultiGenerateInput(BaseModel):
    mode: Literal["multi"] = "multi"
    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=600)
    today: date
    thread_id: str | None = None              # 첫 호출은 None, 서버가 발급

GenerateInput = Annotated[
    SingleGenerateInput | MultiGenerateInput,
    Field(discriminator="mode"),
]

class TaskCandidate(BaseModel):               # 기존 — 변경 없음
    title: str = Field(min_length=1, max_length=80)
    due_date: date
    time_hint: str | None = None
    tags: list[str] = []                      # multi 에서 채워짐

class GenerateResult(BaseModel):              # 후보 확정/검토 단계 응답 (single + multi 공통)
    kind: Literal["candidates"] = "candidates"
    thread_id: str                            # single 도 발급된 값 echo (관찰성)
    todos: list[TaskCandidate]                # due_date == today
    calendar_events: list[TaskCandidate]      # due_date > today
    summary_text: str | None = None           # multi 만 채움 (≤1500자, C3)

class FollowUpResult(BaseModel):              # multi 의 추가 질문 응답
    kind: Literal["follow_up"] = "follow_up"
    thread_id: str
    question: str = Field(max_length=300)
    missing_aspects: list[str]

TurnResult = Annotated[
    GenerateResult | FollowUpResult,
    Field(discriminator="kind"),
]
```

`CommitInput` / `CommitResult` 는 2026-05-24 스펙 그대로.

### 3.2 그래프 상태 (`state.py`)

```python
class Turn(TypedDict):
    role: Literal["user", "assistant"]
    content: str

class ParsedGoal(TypedDict, total=False):
    goal_text: str
    deadline: date | None
    daily_capacity_minutes: int | None
    # 어휘 확정 시점에 확장 (open question §7.1)

class PlanDay(TypedDict):
    date: date
    tasks: list[TaskCandidate]            # tagger 이후 채움

class GenerateState(TypedDict, total=False):
    # required (entry 가 채움)
    mode: Literal["single", "multi"]
    user_id: str
    today: date
    now: datetime

    # single path
    prompt: str
    split_tasks: list[TaskCandidate]

    # multi path
    message: str
    history: list[Turn]
    parsed_goal: ParsedGoal | None
    sufficiency: bool | None
    missing_aspects: list[str]
    follow_up_question: str | None
    plan: list[PlanDay] | None
    summary_text: str | None

    # both — date_router 결과
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]

    # error
    error: Exception | None
```

`turn_count` 필드는 두지 않음 (E7 MAX_TURN 없음 + 단순화). history 길이 / 2 로 도출 가능.

### 3.3 포트 (`protocols.py`)

```python
class LLMPort(Protocol):
    # single
    async def split_tasks(
        self, *, prompt: str, today: date
    ) -> list[TaskCandidate]: ...

    # multi
    async def judge_sufficiency(
        self, *, history: list[Turn], message: str, today: date
    ) -> tuple[bool, list[str], ParsedGoal]: ...

    async def generate_follow_up_question(
        self, *, missing_aspects: list[str], history: list[Turn]
    ) -> str: ...

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]: ...        # (summary_text, days)

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]: ...                    # 각 task 에 tags 부여한 plan
```

### 3.4 Ports 묶음 (`pipeline.py`)

```python
@dataclass
class GeneratePorts:
    llm: LLMPort
```

`config["configurable"]` 에는 `ports`, `now`, `thread_id` (langgraph 자체 키) 주입. checkpointer 는 그래프 컴파일 시점 주입.

---

## 4. 데이터 흐름

### 4.1 single 호출 (stateless 1-shot)

```
POST /todos/generate { mode:'single', user_id, prompt, today }
  ↓
generate_pipeline.run(input, ports, now)
  ↓ thread_id = uuid4()
  ↓ initial state: { mode, user_id, prompt, today, now }
entry → Command(goto='single_validate')
single_validate     (≤200자, 빈/공백 → ValidationError)
task_splitter       (LLMPort.split_tasks, RetryPolicy(3))
date_router         (공유 노드)
END
  ↓
checkpointer.adelete_thread(thread_id)   # cleanup
  ↓
200: GenerateResult { kind:'candidates', thread_id, todos, calendar_events, summary_text=None }
```

### 4.2 multi 첫 turn — 정보 부족 (interrupt)

```
POST /todos/generate { mode:'multi', user_id, message, today }   # thread_id 없음
  ↓
generate_pipeline.run(input, ports, now, thread_id=None)
  ↓ thread_id = uuid4()
  ↓ initial state: { mode, user_id, message, today, now, history=[] }
entry → Command(goto='multi_validate')
multi_validate      (≤600자, 한국어 ≥0.5)
  ↓ history.append({user, message})
planner             (judge_sufficiency)
  ├ sufficiency=False
  └ Command(goto='follow_up')
follow_up
  ↓ generate_follow_up_question → state.follow_up_question
  ↓ interrupt(question)              # checkpointer 가 state persist, 그래프 일시정지
  ↓
200: FollowUpResult { kind:'follow_up', thread_id, question, missing_aspects }
```

### 4.3 multi 후속 turn — resume

```
POST /todos/generate { mode:'multi', user_id, message, today, thread_id }
  ↓
generate_pipeline.run(input, ports, now, thread_id)
  ↓ langgraph 가 thread_id 로 state 로드, Command(resume=input.message)
  ↓
follow_up (resume 분기 — interrupt() 다음 줄부터 재개)
  ↓ history.append({assistant, question}, {user, input.message})
  ↓ → planner (add_edge)
planner
  ├ sufficient=True
  └ Command(goto='plan_generator')
plan_generator
  ↓ generate_plan → (summary_text, days)
  ↓ C3 검증: summary_text > 1500자 시 재생성 1회 → 그래도 위반 시 truncate + log
  ↓ state.plan, state.summary_text
tagger
  ↓ tag_plan → tagged plan
  ↓ 실패 시 빈 태그 degrade + log
date_router         (공유, plan 의 모든 task 평탄화 후 due_date 분리)
END
  ↓
200: GenerateResult { kind:'candidates', thread_id, todos, calendar_events, summary_text }
  ↓
[클라가 검토·수정 후]
POST /todos/commit  # → 기존 commit_graph
```

### 4.4 핵심 보장 (Invariants)

| #  | 보장                                                | 메커니즘                                                                                |
| -- | --------------------------------------------------- | --------------------------------------------------------------------------------------- |
| J1 | single 응답은 stateless                             | 매 호출 새 thread_id, END 후 `checkpointer.adelete_thread(thread_id)` 명시 호출         |
| J2 | multi 같은 thread_id 만 resume 가능                 | langgraph checkpointer thread_id 매칭, 없으면 `ThreadNotFoundError` (4xx)                |
| J3 | 멀티턴 history 누적 보존                            | `state["history"]` in checkpointer (별도 SessionStore 없음)                              |
| J4 | C3 (summary_text ≤1500자) 보장                      | plan_generator 노드 내부 1회 재생성 → 실패 시 truncate + log                            |
| J5 | tagger 실패가 plan 응답을 깨뜨리지 않음             | tagger 노드가 예외 흡수 → 모든 task `tags=[]` degrade + log                              |
| J6 | multi 결과 → commit 정합성                          | date_router 공유 → 동일 `TaskCandidate` 스키마로 normalize                              |
| J7 | single 과 multi state 격리                          | thread_id 단위 격리. single 의 thread 는 즉시 cleanup                                    |
| J8 | 시각 의존 로직 테스트 가능                          | `now: datetime` 을 config 주입                                                          |

---

## 5. 에러 처리

### 5.1 예외 (`exceptions.py`)

기존 (2026-05-24 스펙):

```python
class TodoCreationError(Exception): ...
class ValidationError(TodoCreationError): ...
class AuthorizationError(TodoCreationError): ...
class LLMFailedError(TodoCreationError): ...
class LLMOutputError(TodoCreationError): ...
class SaveFailedError(TodoCreationError): ...
```

신규 (본 스펙):

```python
class ThreadNotFoundError(TodoCreationError): ...   # 4xx — invalid / expired thread_id
```

`MultiTurnError` base / `PlanGenerationError` subclass 는 두지 않음 (단순-사용 YAGNI). C3 위반·빈 plan 은 `LLMOutputError("plan: <reason>")` 메시지로 구분.

### 5.2 노드별 정책

| 노드               | 재시도                                    | 보상/Degrade            | 종착 예외                                  |
| ------------------ | ----------------------------------------- | ----------------------- | ------------------------------------------ |
| `entry`            | 없음                                      | —                       | `ValidationError` (mode 누락/오류)          |
| `single_validate`  | 없음                                      | —                       | `ValidationError` (C1)                      |
| `task_splitter`    | RetryPolicy(3, LLMFailedError) + 파싱 1회 | —                       | `LLMFailedError` / `LLMOutputError`         |
| `date_router`      | —                                         | —                       | —                                          |
| `multi_validate`   | 없음                                      | —                       | `ValidationError` (C2, 한국어 ≥0.5)         |
| `planner`          | RetryPolicy(3, LLMFailedError) + 파싱 1회 | —                       | `LLMFailedError` / `LLMOutputError`         |
| `follow_up`        | RetryPolicy(2, LLMFailedError)            | —                       | `LLMFailedError`                            |
| `plan_generator`   | RetryPolicy(3) + C3 재생성 1회            | C3 초과 → truncate      | `LLMOutputError` ("plan: ...")              |
| `tagger`           | RetryPolicy(2)                            | 실패 → 빈 태그 degrade  | (raise 안 함, 흡수)                         |

### 5.3 thread_id 라이프사이클

| 시나리오                       | 처리                                                                |
| ------------------------------ | ------------------------------------------------------------------- |
| multi 첫 호출 (thread_id=None) | 서버 uuid4() 발급, 응답에 포함                                        |
| multi 후속 호출, 존재          | resume                                                              |
| multi 후속 호출, 없음/만료     | `ThreadNotFoundError` (4xx — 클라가 새 대화 시작)                    |
| 사용자 이탈 후 thread 잔존     | checkpointer TTL — 본 스펙 밖, prod 도입 PR 에서 결정                |
| single 호출                    | uuid4() → END → `adelete_thread` 명시 호출 (MemorySaver 에서도 일관) |

### 5.4 follow_up 무한 루프

E7 — MAX_TURN 강제 없음. 운영 관점 자연 한도(LLM 비용, 사용자 이탈)에 위임. `agents/todo_creation/debug.py` 로그·메트릭으로 관찰성 확보.

### 5.5 HTTP 응답 매핑 (호출자 책임)

| 예외                  | HTTP | body                                   |
| --------------------- | ---- | -------------------------------------- |
| `ValidationError`     | 400  | `{error:"validation", detail:"..."}`   |
| `AuthorizationError`  | 403  | `{error:"forbidden"}`                  |
| `ThreadNotFoundError` | 404  | `{error:"thread_not_found"}`           |
| `LLMFailedError`      | 503  | `{error:"llm_unavailable"}`            |
| `LLMOutputError`      | 502  | `{error:"llm_bad_output"}`             |
| `SaveFailedError`     | 500  | `{error:"save_failed"}`                |

본 스펙은 예외 raise 까지만 책임. FastAPI 라우터가 매핑.

### 5.6 로깅 (`debug.py`)

기존 `debug.py` 의 `log_start` / `log_step` / `log_end` 그대로 사용. `pipeline.run` 에서 `astream(stream_mode=["updates","values"])` 받아 노드별 업데이트마다 호출. multi 의 history 와 user message 는 PII 로 간주, 길이만 로깅 (`docs/AI_RULES.md` 준수).

---

## 6. 테스트 전략

전역 룰: `pyproject` `--cov-fail-under=80`. cov 대상 = `agents/`. 어댑터는 모킹 단위 테스트만.

### 6.1 단위 테스트 — 노드별

| 노드               | 케이스                                                                                                                                  |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `entry`            | mode='single' → goto='single_validate' / mode='multi' → goto='multi_validate' / mode 누락 → ValidationError                              |
| `single_validate`  | 기존 single_turn/test_node_validate.py 그대로 (200/201자 경계, 빈, 공백, user_id, today 형식)                                            |
| `task_splitter`    | 기존 그대로                                                                                                                              |
| `date_router`      | 기존 + multi plan (days·tasks 평탄화) input 케이스 1건 추가                                                                              |
| `multi_validate`   | 600/601자 경계 / 빈 / 공백 / 한국어 음절 ≥0.5 정상 / 한국어 0 거부 / 영어 섞임 허용                                                       |
| `planner`          | 정상 sufficient → goto='plan_generator' / 정상 insufficient → goto='follow_up' / parsed_goal schema 위반 → LLMOutputError / 재시도 후 성공 |
| `follow_up`        | 첫 호출 → interrupt(question) 발생 검증 / resume 시 history 에 assistant question + user answer 두 줄 append                              |
| `plan_generator`   | 정상 / C3 1500자 초과 → 재생성 → 성공 / C3 두 번 초과 → truncate + log / 빈 plan → LLMOutputError                                          |
| `tagger`           | 정상 / LLM 실패 → 모든 task tags=[] degrade, raise 안 함, log                                                                            |

각 노드는 순수 함수 (state → state diff or Command). LangGraph 컴파일 불필요.

### 6.2 통합 테스트 — 통합 generate_graph

`build_generate_graph(checkpointer=MemorySaver())` 컴파일 후 `ainvoke`/`astream`. 페이크 ports + 고정 `now`.

| 시나리오                                            | 기대                                                                                  |
| --------------------------------------------------- | ------------------------------------------------------------------------------------- |
| single happy: 오늘 only                             | todos=1, events=0, `adelete_thread` 호출 검증                                          |
| single happy: 오늘+미래 혼합                        | todos=1, events=1                                                                     |
| single 입력 거부 (prompt 201자)                     | `ValidationError`, thread cleanup 호출됨                                               |
| multi 첫 turn — insufficient                        | `FollowUpResult` 반환, history 길이=1 (user 만), interrupt 발생                         |
| multi 두 turn — 첫 follow_up → resume → sufficient  | `GenerateResult` 반환, history 길이=3, plan + 태그 + date_router 통과                   |
| multi N turn — turn 5에서 sufficient                | `GenerateResult`, history 길이=9                                                       |
| multi LLM 실패 (planner 3회 실패)                   | `LLMFailedError` raise                                                                |
| multi plan_generator C3 위반 1회 → 재생성 성공      | summary_text ≤1500                                                                    |
| multi plan_generator C3 위반 2회                    | summary_text = truncate 결과, 정상 응답                                                 |
| multi tagger 실패                                   | `GenerateResult` 정상, 모든 task tags=[]                                               |
| 다른 thread_id 동시 진행                            | 두 thread state 격리                                                                  |
| 잘못된 thread_id 로 resume                          | `ThreadNotFoundError`                                                                  |

### 6.3 계약 테스트 — 실제 LLM 어댑터

- 단위 (모킹): OpenAI SDK 호출 모킹. 5 메서드 각각 프롬프트·structured output 옵션·반환 파싱 검증.
- 계약 (`@pytest.mark.contract`): `OPENAI_API_KEY` 있으면 실제 호출. 기본 skip.
  - `split_tasks` — 기존
  - `judge_sufficiency` — "내일 토익 보는데 점수 모름" → insufficient + missing_aspects 비어있지 않음
  - `generate_follow_up_question` — missing_aspects=["목표 점수"] → 한국어 질문 반환
  - `generate_plan` — parsed_goal 주고 days≥1, summary_text ≤1500자
  - `tag_plan` — plan 주고 각 task 의 tags ≥0

### 6.4 페이크 LLM (`adapters/todo_creation/fake_llm.py` 통합)

**작업**: 이전 multi-only spec 부산물인 `fake_multi_turn_llm.py` 의 4 메서드를 `fake_llm.py` 로 흡수하고 `fake_multi_turn_llm.py` 삭제. 기존 `fail_times`/`responses` 큐 패턴 유지. mock.AsyncMock 대신 페이크를 두는 이유: 통합 테스트에서 `astream` + `MemorySaver` 시나리오 가독성·재사용성 (character_creation 패턴 일관).

- `split_tasks`: 기존 scripted 응답 큐 (변경 없음)
- `judge_sufficiency`: 큐 — 예: `[(False, ['목표 점수'], {}), (True, [], {goal_text:'토익 800'})]`
- `generate_follow_up_question`: 고정 또는 missing_aspects 기반 템플릿
- `generate_plan`: scripted plan (date range + task count)
- `tag_plan`: 고정 태그 또는 실패 시뮬레이션 옵션

### 6.5 Checkpointer

- 단위/통합 테스트: langgraph 내장 `MemorySaver` 직접 사용 — 별도 어댑터 안 만듦.
- streamlit 데모: `MemorySaver` (단일 프로세스 충분).

---

## 7. 마이그레이션·롤아웃

본 스펙은 단일 PR 또는 다음 4단계 순차 PR 로 진행:

1. **통합 그래프 머지 + 어댑터 통합**
   - `agents/todo_creation/{pipeline,graph,state}.py`, `nodes/entry.py`, `multi_turn/` 추가
   - `adapters/todo_creation/openai_llm.py` 에 4 메서드 흡수 후 `openai_multi_turn.py` 삭제
   - `adapters/todo_creation/fake_llm.py` 에 4 메서드 흡수 후 `fake_multi_turn_llm.py` 삭제
   - 호출처 import 정리 (`from adapters.todo_creation.openai_multi_turn import ...` 등 제거)
   - `tests/adapters/todo_creation/test_openai_multi_turn.py` 의 케이스를 `test_openai_llm.py` 로 흡수 후 원본 삭제
   - 통합 그래프 단위·통합 테스트 80%+
2. **호출처 마이그레이션**
   - `streamlit_app/app.py` 의 `single_turn.pipeline.run` → 최상위 `agents.todo_creation.pipeline.run(SingleGenerateInput(...))` 로 교체
   - multi 데모 페이지 추가 (stretch)
3. **기존 single_turn pipeline 제거**
   - `agents/todo_creation/single_turn/{pipeline.py, graph.py, state.py}` 삭제
   - `tests/agents/todo_creation/single_turn/test_pipeline.py` 삭제 (통합 graph 테스트로 대체)
4. **문서 업데이트**
   - `CHANGELOG.md` 항목 추가
   - `docs/features/todo/architecture.mmd` as-built (multi 분기 + interrupt loop)
   - `docs/features/todo/CLAUDE.md` §4 — "구현 완료, 통합 그래프 참조"

---

## 8. 본 스펙에서 의도적으로 배제

| 항목                                      | 사유                                       | 후속                                          |
| ----------------------------------------- | ------------------------------------------ | --------------------------------------------- |
| Prod checkpointer 어댑터 (Postgres/Redis) | 인프라 결정과 묶임                         | 별도 스펙 (멱등성 통합 안 재검토)              |
| thread TTL / GC 정책                      | 인프라 도입 시점                           | Postgres checkpointer 도입 PR                  |
| 태그 어휘 (자유 vs enum)                  | open Q §7.1                                | 본 스펙: 자유 형식. enum 전환은 별도 PR        |
| 한국어 검증 라이브러리                    | open Q §7.6                                | 본 스펙: 음절 비율 휴리스틱 (≥0.5). lingua 등은 별도 |
| 멀티턴 + commit 통합 (단일 그래프)        | 후속 ④ 스펙에서 결정 보류                  | 운영 데이터 보고 재검토                        |
| HTTP 라우터 / 엔드포인트                  | 호출자 책임                                | FastAPI 통합 PR                                |
| Rate limit                                | 미들웨어 책임                              | 게이트웨이 PR                                  |
| `MAX_TURN` 강제                           | 사용자 결정 — 자연 한도(비용/이탈)에 위임  | 운영 모니터링                                  |
| 멀티턴 plan 의 부분 수정 회귀             | open Q §7.3                                | UX 결정 후 별도 노드                            |
| `time_hint` → 캘린더 시작 시각 변환       | 2026-05-24 D9 그대로                       | 후속                                            |
| `edit_agent` (LLM tool-calling 검토 루프) | 이전 안 폐기 — 클라가 검토·수정 후 commit  | 도입 필요 시 별도 spec                          |

---

## 9. DoD (Definition of Done)

- [ ] `agents/todo_creation/{pipeline,graph,state}.py` 신규, 최상위 직배치
- [ ] `agents/todo_creation/nodes/entry.py` 구현
- [ ] `agents/todo_creation/multi_turn/nodes/{validate,planner,follow_up,plan_generator,tagger}.py` 구현
- [ ] `agents/todo_creation/single_turn/{pipeline.py,graph.py,state.py}` 삭제 (호출처 정리 완료)
- [ ] `agents/todo_creation/single_turn/nodes/{validate,task_splitter,date_router}.py` 통합 그래프에서 재사용 — 변경 없음
- [ ] `agents/todo_creation/commit/` 변경 없음 (회귀 면적 0)
- [ ] `agents/todo_creation/schemas.py` Union 입력 + TurnResult Union 추가
- [ ] `agents/todo_creation/protocols.py` LLMPort 5 메서드 (4 신규)
- [ ] `agents/todo_creation/exceptions.py` `ThreadNotFoundError` 추가
- [ ] `adapters/todo_creation/openai_llm.py` 에 4 신규 메서드 흡수 + 모킹 단위 테스트
- [ ] `adapters/todo_creation/fake_llm.py` 에 4 신규 메서드 흡수 (fail_times/responses 큐 패턴 유지)
- [ ] `adapters/todo_creation/openai_multi_turn.py` 삭제 (호출처 import 정리 완료)
- [ ] `adapters/todo_creation/fake_multi_turn_llm.py` 삭제 (호출처 import 정리 완료)
- [ ] `tests/adapters/todo_creation/test_openai_multi_turn.py` 케이스 흡수 후 삭제
- [ ] `streamlit_app/app.py` 통합 그래프 사용
- [ ] `pytest --cov` 결과 80%+ (`agents/` 기준), §6.1·§6.2 시나리오 모두 통과
- [ ] OpenAI 어댑터 계약 테스트 `OPENAI_API_KEY` 없으면 skip
- [ ] `CHANGELOG.md` 항목 추가 ("multi-turn 도입 + single/multi 통합 generate_graph")
- [ ] `docs/features/todo/architecture.mmd` as-built 갱신
- [ ] `docs/features/todo/CLAUDE.md` §4 멀티턴 노드 책임 → "구현 완료" 표시
