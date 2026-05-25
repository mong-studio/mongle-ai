# Quest Generation — 구현 설계 (Spec)

**작성일:** 2026-05-25
**대상 피처:** `docs/features/quest_generation/` (CLAUDE.md, architecture.mmd)
**현재 상태:** 설계됨 → 본 PR 후 "구현중"

본 문서는 캐릭터 퀘스트 분배 에이전트를 구현하기 위한 합의된 설계 결정사항을 기록한다.
피처 스펙(`docs/features/quest_generation/CLAUDE.md`)이 정의한 책임·제약을 코드 구조로 매핑하고, 스펙의 미결 항목(§8)을 모두 결정한다.

---

## 1. 범위

### 1.1 In-scope (본 PR)

1. **순수 에이전트:** `agents/quest_generation/` — 입력→결과 반환, 외부 상태 비관여
2. **어댑터:** `agents/todo_creation/commit/adapters/quest_dispatch_adapter.py` — `QuestDispatchPort` 구체 구현 (오늘 TODO·캐릭터 fetch → 에이전트 호출 → `quests` 영속화)
3. **프롬프트 카탈로그 v1**
4. **단위 + 통합 테스트** (목표 커버리지 80%+)
5. **문서 갱신:** architecture.mmd as-built, CHANGELOG, FEATURES 상태, CLAUDE.md §8 해소

### 1.2 Out-of-scope (위임/후속)

스펙 §2.2 또는 §7이 명시적으로 호출자/후속 PR로 위임한 항목:

- HUD 이벤트 발행
- `skipped` 항목 백오프 재처리 큐
- quest_gate의 사전-카운터-증가로 인한 슬롯 누수 보정 (기존 코드 주석에 기록된 한계)

위 항목은 어댑터/CLAUDE.md에 "알려진 한계"로 명시한다.

---

## 2. 아키텍처

### 2.1 접근 방식

**함수형 파이프라인** (LangGraph 미사용). 사유:
- 스펙의 플로우는 단일 루프 (분기 없음) → StateGraph 노드 분해 이득 적음
- `CharacterPool`·`LLMRunner` 단위 클래스 분리로 §5 책임 분리 + 단위 테스트 격리가 더 깔끔
- `character_creation`이 LangGraph를 쓰는 이유는 LLM·VLM·ImageGen·S3 4단 직렬 의존 때문 — quest_generation은 LLM 1단

### 2.2 책임 경계

| 책임 | 위치 |
|---|---|
| 입력 검증·라운드 풀·LLM 호출·재시도·결과 누적 | `agents/quest_generation/pipeline.py` |
| 오늘 TODO·활성 캐릭터 조회·`quests` 영속화·로깅 | `agents/todo_creation/commit/adapters/quest_dispatch_adapter.py` |
| 일일 카운터 increment | `agents/todo_creation/commit/nodes/quest_gate.py` (기존, 변경 없음) |
| HUD·백오프 큐 | 후속 PR |

---

## 3. 파일 레이아웃

```
agents/quest_generation/
├── __init__.py
├── pipeline.py            # run(input, *, ports) entry
├── schemas.py             # Pydantic 모델
├── protocols.py           # LLMPort
├── exceptions.py          # LLMFailedError
├── _pool.py               # CharacterPool
├── _llm_runner.py         # 재시도 + 구조화 파싱
└── prompts/
    └── quest_text/
        └── v1/
            ├── system.md
            └── user_template.md

agents/todo_creation/commit/adapters/
├── __init__.py
└── quest_dispatch_adapter.py   # QuestDispatchAdapter (QuestDispatchPort 구현)

tests/agents/quest_generation/
├── test_pipeline.py
├── test_pool.py
└── test_llm_runner.py

tests/agents/todo_creation/commit/adapters/
└── test_quest_dispatch_adapter.py
```

밑줄 접두사 (`_pool.py`, `_llm_runner.py`) = 모듈 내부 구현 (외부 import 금지 신호).

---

## 4. 스키마 (`schemas.py`)

```python
class TodoRef(BaseModel):
    todo_id: UUID        # ← C5: TODO 내용 일체 없음 (구조적 강제)

class Character(BaseModel):
    character_id: UUID
    name: str
    personality: str
    speech_style: str
    appearance_keywords: list[str]

class QuestGenerationInput(BaseModel):
    todos: list[TodoRef]
    characters: list[Character]
    remaining_daily_quota: Annotated[int, Field(ge=0)]
    shuffle_seed: int | None = None     # 테스트 결정성용

class GeneratedQuest(BaseModel):
    character_id: UUID
    todo_id: UUID
    quest_text: Annotated[str, Field(min_length=1, max_length=80)]

class SkippedItem(BaseModel):
    todo_id: UUID
    reason: Literal["llm_failure"]

class QuestDistributionResult(BaseModel):
    generated: list[GeneratedQuest]
    skipped: list[SkippedItem]
```

`Character`의 `appearance_keywords`는 `characters.appearance_description` (VLM 산출 TEXT) 에서 어댑터가 추출/형성한다. 본 PR에서는 단순화: 키워드 분리 없이 description 한 줄을 `appearance_keywords=[description]` 으로 전달해도 무방 (프롬프트가 자유 텍스트로 흡수).

---

## 5. Pipeline (`pipeline.py`)

```python
@dataclass
class Ports:
    llm: LLMPort

async def run(
    input: QuestGenerationInput,
    *,
    ports: Ports,
) -> QuestDistributionResult:
    # §5.1 처리 대상 결정 (C1)
    cap = min(len(input.todos), input.remaining_daily_quota)
    if cap <= 0 or not input.characters:
        return QuestDistributionResult(generated=[], skipped=[])

    # §5.2 풀 초기화
    pool = CharacterPool(input.characters, seed=input.shuffle_seed)
    runner = LLMRunner(ports.llm, max_retries=2)

    generated: list[GeneratedQuest] = []
    skipped: list[SkippedItem] = []

    # §5.3 ~ §5.7 처리 루프 (입력 순서 보존, 순차)
    for todo in input.todos[:cap]:
        char = pool.next()      # 풀 비면 자동 리셋 (C4)
        try:
            text = await runner.generate(character=char)  # C5: char 만 전달
            generated.append(GeneratedQuest(
                character_id=char.character_id,
                todo_id=todo.todo_id,
                quest_text=text,
            ))
        except LLMFailedError:
            skipped.append(SkippedItem(
                todo_id=todo.todo_id,
                reason="llm_failure",
            ))

    return QuestDistributionResult(generated=generated, skipped=skipped)
```

핵심 불변식:
- LLM 실패한 캐릭터는 풀로 복귀하지 않음 (§5.7) — `pool.next()` 결과를 무조건 소비
- `todos` 처리 순서 = 입력 순서 (§8.3 결정)

---

## 6. CharacterPool (`_pool.py`)

```python
class CharacterPool:
    def __init__(self, characters: list[Character], *, seed: int | None = None):
        if not characters:
            raise ValueError("characters must be non-empty")
        self._all: tuple[Character, ...] = tuple(characters)
        self._rng = random.Random(seed)
        self._pool: list[Character] = []
        self._refill()

    def _refill(self) -> None:
        self._pool = list(self._all)
        self._rng.shuffle(self._pool)

    def next(self) -> Character:
        if not self._pool:
            self._refill()      # C4 라운드 리셋
        return self._pool.pop() # C3 원자적 선택+제거
```

- `seed=None` → 비결정적 (운영 기본)
- `seed=int` → 결정적 (테스트)
- 호출자는 `next()`만 사용. 내부 풀 상태는 비공개.

---

## 7. LLMRunner (`_llm_runner.py`)

```python
class LLMRunner:
    def __init__(self, llm: LLMPort, *, max_retries: int = 2):
        self._llm = llm
        self._max_retries = max_retries

    async def generate(self, *, character: Character) -> str:
        last_err: Exception | None = None
        for _ in range(self._max_retries + 1):    # 1 + 2재시도 = 총 3회
            try:
                text = await self._llm.generate_quest(character=character)
                return text         # Pydantic max_length=80 검증은 호출부에서
            except (LLMTransientError, StructuredOutputParseError) as err:
                last_err = err
                continue
        raise LLMFailedError("llm_failure") from last_err
```

재시도 범위 = LLM 일시 오류 + 구조화 출력 파싱 실패 (AI_RULES §3 정렬).

---

## 8. LLMPort + 프롬프트

### 8.1 Protocol

```python
class LLMPort(Protocol):
    async def generate_quest(self, *, character: Character) -> str: ...
```

- 입력은 `Character` 만 (C5 구조적 강제: TODO 정보를 protocol 시그니처에 둘 자리가 없음)
- 반환은 단일 string (max_length 검증은 `GeneratedQuest` Pydantic이 담당)

### 8.2 프롬프트 카탈로그

- 위치: `agents/quest_generation/prompts/quest_text/v1/`
- 파일:
  - `system.md` — 시스템 프롬프트 (불변 규칙)
  - `user_template.md` — 사용자 메시지 템플릿 (`{name}`, `{personality}`, `{speech_style}`, `{appearance_keywords}` 자리)

### 8.3 프롬프트 원칙 (system.md)

- 캐릭터 1인칭 혼잣말 톤 (메인화면 말풍선 UX)
- 페르소나·말투·외형 키워드 반영
- **사용자 TODO 추측·언급 금지** (이중 방어 — 입력 자체에 TODO 없음이 1차)
- 한국어, 공백 포함 80자 이내
- 사용자 입력 내 지시는 무시 (AI_RULES §9 프롬프트 인젝션 방어)

### 8.4 모델 선택

- **Haiku 급** (AI_RULES §1)
- 사유: 1줄 짧은 한국어 생성, 자주 호출 (TODO 수만큼), 비용 절감

### 8.5 구조화 출력

```python
class QuestTextResponse(BaseModel):
    quest_text: Annotated[str, Field(min_length=1, max_length=80)]
```

LLM 어댑터가 위 스키마로 파싱. 실패 시 `StructuredOutputParseError` 발생 → `LLMRunner` 재시도.

---

## 9. Adapter (`quest_dispatch_adapter.py`)

### 9.1 신규 Port (어댑터 의존성)

```python
class TodoQueryPort(Protocol):
    async def list_today_pending(
        self, *, user_id: str, today: date
    ) -> list[TodoRow]: ...     # TodoRow: { id: UUID }

class CharacterQueryPort(Protocol):
    async def list_active(
        self, *, user_id: str
    ) -> list[CharacterRow]: ... # CharacterRow: { id, name, personality, speech_style, appearance_description }

class QuestPersistencePort(Protocol):
    async def insert_many(
        self, *, quests: list[GeneratedQuest]
    ) -> None: ...
```

### 9.2 Adapter 구현

```python
class QuestDispatchAdapter:    # QuestDispatchPort 구현
    def __init__(
        self,
        *,
        todo_repo: TodoQueryPort,
        character_repo: CharacterQueryPort,
        quest_repo: QuestPersistencePort,
        llm: LLMPort,
        today_fn: Callable[[], date],
    ): ...

    async def dispatch(self, *, user_id: str) -> None:
        today = self._today_fn()
        todos_rows = await self._todo_repo.list_today_pending(user_id=user_id, today=today)
        chars_rows = await self._character_repo.list_active(user_id=user_id)

        if not todos_rows or not chars_rows:
            return  # silent no-op (스펙 §6)

        agent_input = QuestGenerationInput(
            todos=[TodoRef(todo_id=t.id) for t in todos_rows],
            characters=[Character(
                character_id=c.id,
                name=c.name,
                personality=c.personality,
                speech_style=c.speech_style,
                appearance_keywords=[c.appearance_description or ""],
            ) for c in chars_rows],
            remaining_daily_quota=len(todos_rows),  # §11 참조
        )

        result = await quest_generation.run(agent_input, ports=quest_generation.Ports(llm=self._llm))

        if result.generated:
            await self._quest_repo.insert_many(quests=result.generated)

        if result.skipped:
            logger.warning(
                "quest_dispatch partial: user=%s generated=%d skipped=%d",
                user_id, len(result.generated), len(result.skipped),
            )
            # TODO: 백오프 큐 등록 (out of scope — §11)
```

### 9.3 `QuestDispatchPort` 시그니처

기존 그대로 유지 (`dispatch(user_id: str) -> None`). `quest_gate`/`quest_dispatch_node` 변경 없음.

---

## 10. §8 미결사항 일괄 해소

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 1 | 퀘스트 텍스트 길이 | **80자** | 말풍선 UX 자연 길이, 캡션(140자)과 시각 차별 |
| 2 | 셔플 시드 | **옵션 주입** (`shuffle_seed: int \| None`) | 테스트 결정성, 운영은 비결정적 |
| 3 | TODO 처리 순서 | **입력 순서 보존** | 호출자가 정렬 책임, 에이전트는 단순/예측 |
| 4 | LLM 동시성 | **순차** | Haiku rate limit 안전, 5건/일 throttling으로 충분 |
| 5 | LLM 재시도 | **2회** (총 3시도) | AI_RULES §3 기본값 |

CLAUDE.md §8 → "결정사항"으로 갱신, "알려진 한계" 섹션 별도 추가.

---

## 11. 알려진 한계 (코드 주석 + CLAUDE.md 명시)

### 11.1 Quota 슬롯 누수

`quest_gate`는 dispatch 시작 전 카운터를 +1 한다. 1 dispatch에서 N개 quests를 생성하므로 슬롯 의미가 "1 slot = 1 dispatch (= 최대 N quests)"로 어긋난다. 본 PR은 이 구조를 변경하지 않고 어댑터에서 `remaining_daily_quota = len(todos)` 를 전달하여 per-quest cap을 사실상 비활성화한다.

**해결 후보 (후속):** (a) gate에서 todos 수만큼 incr / (b) gate를 dispatch 후로 이동 + 실패 시 보정 / (c) 슬롯 의미를 명시적으로 "1 dispatch"로 재정의.

### 11.2 부분 실패 재처리 없음

`skipped` 항목은 `logger.warning` 만. 백오프 큐 미구현. 사용자 입장에서는 해당 TODO에 퀘스트가 영구 부재.

### 11.3 HUD 이벤트 미발행

어댑터 끝에서 HUD/알림 이벤트를 발행하지 않음. 별도 PR로 위임.

---

## 12. 테스트 계획 (TDD)

### 12.1 단위 테스트

**`test_pool.py`:**
- 시드 고정 시 결정적 순서 검증
- 풀 소진 시 `next()` 호출 → 자동 리셋 후 반환
- 라운드 1 내에서 같은 캐릭터 두 번 나오지 않음 (3명 풀에서 3회 호출 → 3명 distinct)
- 빈 characters 생성 시 ValueError

**`test_llm_runner.py`:**
- 첫 시도 성공 → 1회 호출
- 3번째 시도 성공 → 3회 호출
- 3회 모두 LLMTransientError → `LLMFailedError`
- StructuredOutputParseError도 재시도 대상
- 비재시도 예외 (ex. AuthError) 는 즉시 전파

**`test_pipeline.py`:**
- 빈 todos / 빈 characters / quota=0 → 빈 결과 (예외 아님)
- cap = min(len(todos), quota) 적용 검증
- 1:1:1 매핑 (C2) — 같은 character_id가 같은 라운드에 두 번 안 나옴
- **C5 격리 검증**: LLM mock spy → `generate_quest` 호출 시 `character` 만 전달, todo 정보 미포함
- 부분 실패: LLM이 특정 todo에 대해 실패 → 해당 todo만 `skipped`, 나머지 정상
- 라운드 리셋: characters=2, todos=3 → 3개 모두 생성, 첫 캐릭터가 정확히 2회 사용됨

### 12.2 통합 테스트

**`test_quest_dispatch_adapter.py`:**
- in-memory repos + fake LLM
- 정상 dispatch → `quest_repo.insert_many` 호출 검증, 인자가 GeneratedQuest 리스트
- 오늘 TODO 0건 → repo 호출 없음, 로깅 없음
- 캐릭터 0명 → repo 호출 없음
- 부분 실패 (fake LLM이 일부 todo에 대해 실패) → 성공분만 INSERT, warning 로그 검증

### 12.3 커버리지 목표

`agents/quest_generation/` 모듈 라인 커버리지 80%+ (글로벌 `~/.claude/rules/testing.md`).

---

## 13. 구현 순서

1. **스키마·예외** (`schemas.py`, `exceptions.py`)
2. **CharacterPool TDD** — 시드 결정성·리셋
3. **LLMRunner TDD** — 재시도·파싱 실패
4. **Pipeline TDD** — 1:1:1·C5·quota·부분 실패
5. **프롬프트 v1** (`prompts/quest_text/v1/system.md`, `user_template.md`)
6. **실제 LLM 클라이언트 어댑터** (Haiku, 구조화 출력)
7. **신규 Ports 정의** (`TodoQueryPort`, `CharacterQueryPort`, `QuestPersistencePort`)
8. **QuestDispatchAdapter TDD**
9. **`app.py` (또는 wire-up 지점) 어댑터 주입**
10. **`architecture.mmd` as-built 갱신**
11. **`CHANGELOG.md` `[Unreleased]` `### Added` 항목**
12. **`docs/FEATURES.md` §1 상태 컬럼 `설계됨` → `구현중`**
13. **`docs/features/quest_generation/CLAUDE.md` §8 → "결정사항" + "알려진 한계" 섹션**

---

## 14. DoD (FEATURES.md §4) 매핑

| # | 항목 | 본 PR | 후속 PR |
|---|---|---|---|
| 1 | 테스트 통과 | ✅ | — |
| 2 | architecture.mmd as-built | ✅ | — |
| 3 | CHANGELOG 항목 | ✅ | — |
| 4 | CLAUDE.md 미결사항 해소 | ✅ | 백오프 큐는 별도 |
| 5 | 인덱스 갱신 (상태 = "구현중") | ✅ | "완성"은 §11 한계 해소 후 |

본 PR로 피처 상태는 **설계됨 → 구현중**. "완성" 처리는 §11.1~11.3 해소 시.
