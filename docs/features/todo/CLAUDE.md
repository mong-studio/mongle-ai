# TODO 자동 생성 AI Agent 설계서

**관련 문서:**
- 제품 컨텍스트: [../../PRODUCT_SPEC.md](../../PRODUCT_SPEC.md)
- 피처 인덱스·공통 패턴·DoD: [../../FEATURES.md](../../FEATURES.md)
- 공통 AI 규칙: [../../AI_RULES.md](../../AI_RULES.md)
- 데이터 모델: [../../DATA_MODEL.md](../../DATA_MODEL.md) — §3 (TODO/일정/퀘스트), §3.4 (tags)
- 아키텍처 다이어그램: [./architecture.mmd](./architecture.mmd)

---

> 몽글마을 — TODO/플랜 생성 파이프라인 하네스(Harness) 구조 작성을 위한 참고 문서.

---

## 1. 목적 (Goal)

사용자의 자연어 입력으로부터 두 가지 경로로 TODO 및 캘린더 일정을 생성한다.

- **싱글턴 모드**: 한 번의 프롬프트로 여러 task를 즉시 분할하여 TODO/캘린더에 등록
- **멀티턴 모드**: 장기 플랜에 대해 챗봇과의 대화를 통해 일자별 플랜을 점진적으로 구체화

두 경로 모두 최종적으로 동일한 저장 디스패처를 거치며, 당일 TODO 생성/확정 시 캐릭터 퀘스트 분배 에이전트가 트리거된다.

---

## 2. 입력 / 출력 (I/O Contract)

### 2.1 싱글턴 Input

| 필드      | 타입   | 필수 | 비고                                   |
| --------- | ------ | ---- | -------------------------------------- |
| `user_id` | string | ✅   | 인증된 사용자 식별자                   |
| `prompt`  | string | ✅   | 자연어 프롬프트, **공백 포함 ≤ 200자** |
| `today`   | date   | ✅   | 상대 날짜 표현 해석 기준 (서버 시각)   |

### 2.2 멀티턴 Input

| 필드         | 타입   | 필수 | 비고                                              |
| ------------ | ------ | ---- | ------------------------------------------------- |
| `user_id`    | string | ✅   | 인증된 사용자 식별자                              |
| `message`    | string | ✅   | 자연어 메시지, **공백 포함 ≤ 600자**, 한국어 위주 |
| `session_id` | string | ✅   | 멀티턴 대화 세션 식별자                           |
| `today`      | date   | ✅   | 상대 날짜 표현 해석 기준                          |

### 2.3 공통 Output (확정 후)

```json
{
  "todos": [
    {
      "todo_id": "uuid",
      "title": "...",
      "due_date": "YYYY-MM-DD",
      "tags": ["..."],
      "source": "single | multi"
    }
  ],
  "calendar_events": [
    {
      "event_id": "uuid",
      "title": "...",
      "date": "YYYY-MM-DD",
      "tags": ["..."]
    }
  ],
  "quest_distribution_triggered": true | false
}
```

---

## 3. 제약사항 (Constraints)

| ID  | 항목                      | 값                                                          |
| --- | ------------------------- | ----------------------------------------------------------- |
| C1  | 싱글턴 프롬프트 길이      | 공백 포함 **≤ 200자**                                       |
| C2  | 멀티턴 사용자 입력 길이   | 공백 포함 **≤ 600자**, 한국어 위주                          |
| C3  | LLM 플랜 응답 길이        | 공백 포함 **≤ 1500자** (한국어)                             |
| C4  | 캐릭터 퀘스트 분배 트리거 | **당일 TODO 생성/확정 시**, **일일 5회 한도**               |
| C5  | 미래 날짜 task 처리       | 싱글턴에서 오늘이 아닌 날짜 task는 **캘린더 일정**으로 등록 |
| C6  | 태그 자동 부여            | 멀티턴 확정 시, **목표 기반 태그를 일정/TODO에 자동 부여**  |

위반 시 파이프라인을 실행하지 않고 즉시 에러를 반환한다 (C1, C2). C3는 LLM 출력 검증으로 처리.

---

## 4. 노드별 책임 (Node Responsibilities)

### 4.1 싱글턴 — Validation

- **검사:** 프롬프트 길이(C1), 빈 입력
- **실패 시:** 즉시 4xx, LLM 미호출
- **부수효과:** 없음

### 4.2 싱글턴 — LLM (Task Splitter)

- **Input:** `prompt`, `today` (상대 날짜 해석 컨텍스트)
- **Output (구조화):**
  ```json
  [
    {
      "title": "코딩테스트 1회차",
      "due_date": "2026-05-22",
      "time_hint": "오전"
    },
    { "title": "면접 스터디", "due_date": "2026-05-22", "time_hint": "저녁" },
    { "title": "프로젝트 발표", "due_date": "2026-05-25", "time_hint": null }
  ]
  ```
- **제약:** 출력은 JSON 스키마 강제 (구조화 출력)
- **주의:** "3일 뒤"같은 상대 표현 해석은 LLM 책임. `today`를 시스템 프롬프트에 명시.

### 4.3 싱글턴 — 날짜 라우팅

- **순수 로직 (LLM 아님)**
- **Input:** Task Splitter 출력
- **분기:** `due_date == today` → 오늘의 TODO 후보 / 그 외 → 캘린더 일정 후보
- **Output:** `{ todos: [...], calendar_events: [...] }`

### 4.4 싱글턴 — 사용자 확인/수정 UI

- **책임:** 후보 목록을 사용자에게 보여주고 수정/삭제/확정 받기
- **하네스 경계:** 백엔드는 후보를 임시 상태(또는 클라이언트 측 상태)로 전달, 확정 요청 시 저장 디스패처 호출

### 4.5 멀티턴 — Validation

- **검사:** 메시지 길이(C2), 빈 입력
- **실패 시:** 즉시 4xx

### 4.6 멀티턴 — LLM (Planner / Sufficiency Judge)

- **Input:** 현재 메시지 + `session_id`로 조회한 이전 대화 히스토리
- **Output (구조화):**
  ```json
  {
    "is_sufficient": true | false,
    "missing_aspects": ["목표 점수", "하루 가용 시간"],
    "parsed_goal": { ... }
  }
  ```
- **책임:** 정보 충분성 판단. 부족 시 어느 측면이 비어있는지 명시.

### 4.7 멀티턴 — LLM (Follow-up Question Generator)

- **Input:** Planner의 `missing_aspects`
- **Output:** 사용자에게 보여줄 한국어 꼬리 질문 텍스트
- **루프:** 사용자 답변 후 다시 Planner로 회귀

### 4.8 멀티턴 — LLM (Plan Generator)

- **Input:** 충분히 수집된 목표 정보
- **Output (구조화):**
  ```json
  {
    "summary_text": "...",
    "days": [
      { "date": "YYYY-MM-DD", "tasks": [{ "title": "...", "detail": "..." }] }
    ]
  }
  ```
- **제약 (C3):** `summary_text` 공백 포함 ≤ 1500자. 초과 시 재생성 또는 잘라내기 정책 결정 필요.

### 4.9 멀티턴 — LLM (Tagger)

- **Input:** Plan Generator 출력 + parsed_goal
- **Output:** 각 day/task에 부여할 태그 배열
- **책임:** 사용자 목표에 부합하는 태그 생성. 태그 어휘는 자유 형식 vs 사전 정의 enum 중 결정 필요 (미결 사항).

### 4.10 멀티턴 — 사용자 확인/수정 UI

- **책임:** 플랜 + 태그를 사용자가 검토. 수정/삭제 요청 시 Planner로 회귀 가능.

### 4.11 저장 디스패처 (공통)

- **Input:** 확정된 `{ todos, calendar_events, tags }`
- **책임:**
  - TODO DB / Calendar DB에 각각 저장 (트랜잭션)
  - 저장 결과로 당일 TODO 생성/확정 발생 여부 판정 → 퀘스트 분배 트리거
- **원자성:** TODO와 Calendar 저장이 동시 실패 시 롤백 필요

### 4.12 캐릭터 퀘스트 분배 Agent

- **트리거 조건:** 당일 TODO 생성 또는 확정
- **호출 한도 (C4):** **일일 5회**, 초과 시 트리거 무시 (에러 아님, silent skip)
- **카운트 키:** `quest_distribute:{user_id}:{YYYY-MM-DD}` Redis 카운터 권장
- **상세:** 본 문서 범위 밖, 별도 문서 참조

---

## 5. 하네스(Harness) 구조 가이드

### 5.1 디렉토리 레이아웃 (예시)

```
agents/todo_creation/
├── __init__.py
├── single_turn/
│   ├── pipeline.py        # 싱글턴 오케스트레이션
│   ├── validation.py
│   ├── task_splitter.py   # 4.2
│   └── date_router.py     # 4.3
├── multi_turn/
│   ├── pipeline.py        # 멀티턴 오케스트레이션
│   ├── validation.py
│   ├── planner.py         # 4.6
│   ├── follow_up.py       # 4.7
│   ├── plan_generator.py  # 4.8
│   └── tagger.py          # 4.9
├── commit/
│   ├── dispatcher.py      # 4.11
│   └── quest_trigger.py   # 4.12 호출 게이트
├── schemas.py             # 공통 Pydantic 모델
├── repository.py          # TODO / Calendar DB I/O
└── exceptions.py
```

### 5.2 인터페이스 스케치

```python
# schemas.py
class SingleTurnInput(BaseModel):
    user_id: str
    prompt: str = Field(max_length=200)
    today: date

class MultiTurnInput(BaseModel):
    user_id: str
    session_id: str
    message: str = Field(max_length=600)
    today: date

class TaskCandidate(BaseModel):
    title: str
    due_date: date
    time_hint: str | None
    tags: list[str] = []

class CommitPayload(BaseModel):
    user_id: str
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]
    source: Literal["single", "multi"]

class CommitResult(BaseModel):
    todo_ids: list[UUID]
    event_ids: list[UUID]
    quest_distribution_triggered: bool


# single_turn/pipeline.py
async def run(input: SingleTurnInput) -> list[TaskCandidate]:
    validation.check(input)
    tasks = await task_splitter.split(input.prompt, today=input.today)
    todos, events = date_router.route(tasks, today=input.today)
    return todos + events  # UI로 반환, 사용자 확정 대기


# multi_turn/pipeline.py
async def turn(input: MultiTurnInput) -> PlannerTurnResult:
    validation.check(input)
    history = await session_store.get(input.session_id)
    judgment = await planner.judge(history, input.message)

    if not judgment.is_sufficient:
        question = await follow_up.ask(judgment.missing_aspects)
        await session_store.append(input.session_id, input.message, question)
        return PlannerTurnResult(kind="question", text=question)

    plan = await plan_generator.generate(judgment.parsed_goal)
    tagged_plan = await tagger.tag(plan, judgment.parsed_goal)
    return PlannerTurnResult(kind="plan", plan=tagged_plan)


# commit/dispatcher.py
async def commit(payload: CommitPayload) -> CommitResult:
    async with db.transaction():
        todo_ids = await repository.save_todos(payload.todos, payload.user_id)
        event_ids = await repository.save_events(payload.calendar_events, payload.user_id)

    triggered = await quest_trigger.maybe_dispatch(
        user_id=payload.user_id,
        has_today_todo=any(t.due_date == today() for t in payload.todos),
    )
    return CommitResult(todo_ids=todo_ids, event_ids=event_ids, quest_distribution_triggered=triggered)
```

---

## 6. 에러 처리 (Error Handling)

| 단계                               | 실패 시 처리                                           |
| ---------------------------------- | ------------------------------------------------------ |
| Validation (C1/C2)                 | 즉시 4xx, LLM 미호출                                   |
| LLM 호출 (모든 단계)               | 재시도 2회, 실패 시 5xx                                |
| 구조화 출력 파싱 실패              | 재시도 1회 (스키마 명시 강화), 실패 시 5xx             |
| Plan Generator 출력 길이 초과 (C3) | 재생성 1회, 실패 시 잘라내기 또는 5xx (정책 결정 필요) |
| 저장 디스패처 (DB)                 | 트랜잭션 롤백, 5xx                                     |
| 퀘스트 트리거 (C4 초과)            | **silent skip**, 메인 응답에는 영향 없음               |
| 퀘스트 에이전트 호출 실패          | TODO 저장은 성공으로 처리, 분배는 별도 백오프 큐로     |

---

## 7. 결정 사항 (이전 미결 사항 해결)

| #  | 항목                              | 결정                                                          | 출처 |
|----|----------------------------------|--------------------------------------------------------------|------|
| Q1 | 태그 어휘 (Tagger)                  | 자유 형식 문자열                                                  | 2026-05-25 multi_turn 설계 |
| Q2 | 멀티턴 세션 저장소                       | 커스텀 `SessionStorePort` (in-memory → MySQL)                    | 2026-05-25 multi_turn 설계 |
| Q3 | 수정 회귀 범위                         | edit_agent → plan_generator 직진 (Planner 거치지 않음)          | 2026-05-25 multi_turn 설계 |
| Q4 | 싱글턴 time_hint 처리                | 별도 결정 필요 (싱글턴 영역)                                          | 미결 |
| Q5 | Plan Generator C3 초과              | 재생성 1회 → 실패 시 마침표 기준 잘라내기                                | 2026-05-25 multi_turn 설계 |
| Q6 | 한국어 위주 검증                      | 한글 유니코드 비율 ≥ 0.3 휴리스틱                                    | 2026-05-25 multi_turn 설계 |
| Q7 | 퀘스트 분배 카운트 리셋                  | 기존 commit 모듈 결정 유지 (KST 자정)                                | PR #6 |

---

## 8. 참고

- 본 문서는 **하네스/오케스트레이션 레이어** 설계를 위한 것이며, 각 LLM의 프롬프트 디테일은 별도 프롬프트 카탈로그 문서에서 관리한다.
- 캐릭터 퀘스트 분배 에이전트 내부 동작은 `docs/features/quest_generation/` 문서 참조.
- 캘린더 UI/UX 사양(연속 일정 표시, 색 구분 등)은 본 파이프라인 범위 밖이며, 프론트엔드 사양 문서 참조.
