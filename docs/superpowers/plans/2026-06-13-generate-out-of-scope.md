# 단일턴 generate out_of_scope 처리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 단일 `POST /v1/todo/generate` 가 "배고프다" 같은 비-목표 입력을 억지 todo 로 만들지 않고 `OutOfScopeResult` 로 응답하게 한다.

**Architecture:** 기존 `split_tasks` LLM 1회 호출 출력에 `intent`("plan"|"out_of_scope")를 합친다(추가 LLM 호출 없음). `split_tasks` 반환 타입을 `SplitResult(intent, tasks)` 로 바꾸고, 단일 그래프 `task_splitter` 뒤에 조건 분기를 추가해 out_of_scope 면 `date_router` 를 건너뛰고 `OutOfScopeResult` 를 반환한다. 멀티턴 플래너의 `OutOfScopeResult`·안내문구를 공유한다.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, pydantic v2, pytest(asyncio).

**Spec:** `docs/superpowers/specs/2026-06-13-generate-out-of-scope-design.md`

---

## File Structure

- `agents/todo_creation/schemas.py` — `OUT_OF_SCOPE_MESSAGE` 상수, `SplitResult` 타입, `SingleTurnResult` 유니온 추가
- `agents/todo_creation/planner/nodes/out_of_scope.py` — 로컬 `_OUT_OF_SCOPE_MESSAGE` 를 공유 상수로 교체
- `agents/todo_creation/protocols.py` — `LLMPort.split_tasks` 반환타입 `SplitResult`
- `adapters/todo_creation/qwen_llm.py` — `parse_task_response`/`split_tasks` 가 intent 파싱
- `adapters/todo_creation/_prompts.py` — `TASK_SPLITTER_SYSTEM` intent 규칙·예시
- `agents/todo_creation/todo/state.py` — `intent` 필드, `result` 타입 확장
- `agents/todo_creation/todo/nodes/task_splitter.py` — out_of_scope 분기
- `agents/todo_creation/todo/nodes/out_of_scope.py` (신규) — `OutOfScopeResult` 생성 노드
- `agents/todo_creation/todo/pipeline.py` — 조건 분기 엣지 + 라우터 함수
- `api/todo_creation/router.py` — `/generate` 응답모델 `Envelope[SingleTurnResult]`
- 테스트: `fake_llm.py`, `test_qwen_llm.py`, `test_fake_llm.py`, `test_task_splitter.py`, `test_pipeline.py`(todo), `test_prompts.py`, `test_todo_generate.py`

---

## Task 1: 공유 상수·타입·유니온 (schemas)

**Files:**
- Modify: `agents/todo_creation/schemas.py`
- Modify: `agents/todo_creation/planner/nodes/out_of_scope.py`
- Test: `tests/agents/todo_creation/test_schemas.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/agents/todo_creation/test_schemas.py` 끝에 추가

```python
def test_single_turn_result_discriminates_out_of_scope() -> None:
    from pydantic import TypeAdapter
    from agents.todo_creation.schemas import SingleTurnResult, OutOfScopeResult

    adapter = TypeAdapter(SingleTurnResult)
    parsed = adapter.validate_python(
        {"kind": "out_of_scope", "thread_id": "", "message": "안내"}
    )
    assert isinstance(parsed, OutOfScopeResult)


def test_split_result_holds_intent_and_tasks() -> None:
    from agents.todo_creation.schemas import SplitResult, TaskCandidate
    from datetime import date

    r = SplitResult(intent="plan", tasks=[TaskCandidate(title="x", due_date=date(2026, 6, 13))])
    assert r.intent == "plan"
    assert len(r.tasks) == 1


def test_out_of_scope_message_constant_nonempty() -> None:
    from agents.todo_creation.schemas import OUT_OF_SCOPE_MESSAGE

    assert isinstance(OUT_OF_SCOPE_MESSAGE, str) and len(OUT_OF_SCOPE_MESSAGE) > 0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/agents/todo_creation/test_schemas.py -q`
Expected: FAIL — `ImportError: cannot import name 'SingleTurnResult'`(및 SplitResult/OUT_OF_SCOPE_MESSAGE)

- [ ] **Step 3: schemas.py 구현** — 파일 상단 import 에 `dataclass` 추가, 끝부분에 상수·타입 추가

`from __future__ import annotations` 아래 import 블록에 추가:
```python
from dataclasses import dataclass
```

파일 맨 끝(기존 `TurnResult` 정의 다음)에 추가:
```python
OUT_OF_SCOPE_MESSAGE = (
    "나는 목표를 TODO랑 일정으로 차근차근 나눠주는 이장님이야. "
    "준비할 일이나 이루고 싶은 목표를 말해주면 같이 계획을 짜볼게."
)


@dataclass(frozen=True)
class SplitResult:
    """단일턴 split_tasks 의 출력: 범위 판단(intent) + 후보 목록."""

    intent: Literal["plan", "out_of_scope"]
    tasks: list[TaskCandidate]


SingleTurnResult = Annotated[
    GenerateResult | OutOfScopeResult,
    Field(discriminator="kind"),
]
```

> `Literal`, `Annotated`, `Field` 는 schemas.py 상단에서 이미 import 됨(기존 `TurnResult` 가 사용). 확인만 하고 중복 추가하지 말 것.

- [ ] **Step 4: planner out_of_scope 노드를 공유 상수로 교체** — `agents/todo_creation/planner/nodes/out_of_scope.py`

기존 로컬 상수 정의 삭제:
```python
_OUT_OF_SCOPE_MESSAGE = (
    "나는 목표를 TODO랑 일정으로 차근차근 나눠주는 이장님이야. "
    "준비할 일이나 이루고 싶은 목표를 말해주면 같이 계획을 짜볼게."
)
```
상단 import 추가:
```python
from agents.todo_creation.schemas import OUT_OF_SCOPE_MESSAGE
```
`out_of_scope_node` 본문에서 `_OUT_OF_SCOPE_MESSAGE` → `OUT_OF_SCOPE_MESSAGE` 로 교체:
```python
    return {
        "out_of_scope_message": OUT_OF_SCOPE_MESSAGE,
        "todos": [],
        "calendar_events": [],
    }
```

- [ ] **Step 5: 테스트 통과 확인 (회귀 포함)**

Run: `uv run pytest tests/agents/todo_creation/test_schemas.py tests/agents/todo_creation/planner -q`
Expected: PASS (planner out_of_scope 동작 동일, 문구 동일)

- [ ] **Step 6: Commit**

```bash
git add agents/todo_creation/schemas.py agents/todo_creation/planner/nodes/out_of_scope.py tests/agents/todo_creation/test_schemas.py
git commit -m "feat: SplitResult·SingleTurnResult·공유 OUT_OF_SCOPE_MESSAGE 추가"
```

---

## Task 2: split_tasks 를 SplitResult 로 마이그레이션 (intent 파싱)

> 프로토콜 반환타입을 바꾸므로 생산자(parser/qwen)·소비자(node)·fake 3곳·관련 테스트를 한 태스크에서 함께 이동해 전체 스위트를 green 으로 유지한다. 동작(out_of_scope 분기)은 Task 4에서 추가하고, 여기서는 **타입만** 옮긴다(기존 plan 동작 보존).

**Files:**
- Modify: `adapters/todo_creation/qwen_llm.py` (`parse_task_response`, `split_tasks`)
- Modify: `agents/todo_creation/protocols.py`
- Modify: `agents/todo_creation/todo/nodes/task_splitter.py`
- Modify: `tests/agents/todo_creation/fake_llm.py`
- Modify: `tests/adapters/todo_creation/test_qwen_llm.py`, `tests/adapters/todo_creation/test_fake_llm.py`
- Modify: `tests/api/test_todo_generate.py` (fake), `tests/agents/todo_creation/planner/test_pipeline.py` (stub)

- [ ] **Step 1: 파서 단위 실패 테스트** — `tests/adapters/todo_creation/test_qwen_llm.py` 에 추가

```python
async def test_split_tasks_returns_split_result_with_plan_intent() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM
    from agents.todo_creation.schemas import SplitResult

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(json.dumps({
            "intent": "plan",
            "tasks": [{"title": "코테", "due_date": "2026-05-24", "tags": ["학습"]}],
        })))
    ]
    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="오늘 코테", today=date(2026, 5, 24))
    assert isinstance(out, SplitResult)
    assert out.intent == "plan"
    assert out.tasks[0].title == "코테"


async def test_split_tasks_missing_intent_defaults_to_plan() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(json.dumps({
            "tasks": [{"title": "운동가기", "due_date": "2026-05-24", "tags": ["건강"]}],
        })))
    ]
    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="오늘 운동", today=date(2026, 5, 24))
    assert out.intent == "plan"
    assert out.tasks[0].title == "운동가기"


async def test_split_tasks_out_of_scope_returns_empty_tasks() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(json.dumps({"intent": "out_of_scope", "tasks": []})))
    ]
    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="배고프다", today=date(2026, 5, 24))
    assert out.intent == "out_of_scope"
    assert out.tasks == []
```

기존 split 테스트의 단언을 `.tasks` 로 수정(아래 3곳):
- `test_split_tasks_parses_valid_json`: `assert len(out) == 2` → `assert len(out.tasks) == 2`; `out[0]` → `out.tasks[0]`
- `test_split_tasks_strips_code_fence`: `out[0].title` → `out.tasks[0].title`
- `test_split_tasks_retries_once_on_invalid_json`: `out[0].title` → `out.tasks[0].title`
- (재시도 횟수/에러 테스트는 단언이 예외 기반이라 수정 불필요)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/adapters/todo_creation/test_qwen_llm.py -q`
Expected: FAIL — `ImportError: SplitResult` / `TypeError: object is not subscriptable`

- [ ] **Step 3: parse_task_response 구현** — `adapters/todo_creation/qwen_llm.py`

상단 import 에 `SplitResult` 추가(기존 `from agents.todo_creation.schemas import TaskCandidate` 줄을 교체):
```python
from agents.todo_creation.schemas import SplitResult, TaskCandidate
```
`parse_task_response` 를 교체:
```python
def parse_task_response(raw: str) -> SplitResult:
    stripped = strip_json_fence(raw)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as err:
        raise LLMOutputError(f"non-JSON response: {stripped[:200]}") from err

    if not isinstance(parsed, dict):
        raise LLMOutputError(f"not a JSON object: {stripped[:200]}")

    intent = parsed.get("intent")
    if intent not in ("plan", "out_of_scope"):
        intent = "plan"
    if intent == "out_of_scope":
        return SplitResult(intent="out_of_scope", tasks=[])

    if "tasks" not in parsed:
        raise LLMOutputError(f"missing 'tasks' key: {stripped[:200]}")
    tasks_raw = parsed["tasks"]
    if not isinstance(tasks_raw, list):
        raise LLMOutputError("'tasks' is not a list")

    out: list[TaskCandidate] = []
    for item in tasks_raw:
        try:
            out.append(
                TaskCandidate(
                    title=item["title"],
                    due_date=date.fromisoformat(item["due_date"]),
                    tags=item.get("tags") or [],
                )
            )
        except (KeyError, ValueError, TypeError) as err:
            raise LLMOutputError(f"invalid task item {item!r}: {err}") from err
    return SplitResult(intent="plan", tasks=out)
```

- [ ] **Step 4: split_tasks 반환타입 변경** — 같은 파일

```python
    async def split_tasks(self, *, prompt: str, today: date) -> SplitResult:
        messages = build_task_splitter_messages(prompt=prompt, today=today)
        last_err: LLMOutputError | None = None

        for attempt in range(2):
            raw = await self.complete_raw(messages=messages, label="split_tasks")
            try:
                return parse_task_response(raw)
            except LLMOutputError as err:
                last_err = err
                log.warning(
                    "qwen split_tasks parse fail (attempt %d): %s",
                    attempt + 1,
                    err,
                )
                messages = reinforce_messages(messages, raw_response=raw)

        assert last_err is not None
        raise last_err
```

- [ ] **Step 5: 프로토콜 반환타입 변경** — `agents/todo_creation/protocols.py`

import 에 `SplitResult` 추가:
```python
from agents.todo_creation.schemas import (
    CommitResult,
    SplitResult,
    TaskCandidate,
)
```
`split_tasks` 시그니처:
```python
    async def split_tasks(
        self, *, prompt: str, today: date
    ) -> SplitResult: ...
```

- [ ] **Step 6: 소비자(node) 를 SplitResult 로** — `agents/todo_creation/todo/nodes/task_splitter.py`

`task_splitter_node` 의 LLM 호출부를 교체(동작은 기존과 동일, intent 무시):
```python
    split = await ports.llm.split_tasks(prompt=state["input"].prompt, today=today)
    raw = split.tasks
    if not raw:
        # B2: one retry on empty
        split = await ports.llm.split_tasks(prompt=state["input"].prompt, today=today)
        raw = split.tasks
        if not raw:
            raise LLMOutputError("task_splitter returned empty list after retry")
```
(이하 `if len(raw) > MAX_TASKS:` 부터는 변경 없음. 반환은 `return {"split_tasks": corrected}` 그대로.)

- [ ] **Step 7: FakeLLM 갱신** — `tests/agents/todo_creation/fake_llm.py`

상단 import 교체 및 클래스 수정:
```python
from agents.todo_creation.schemas import SplitResult, TaskCandidate


@dataclass
class FakeLLM:
    responses: list[list[TaskCandidate]] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    fail_times: int = 0
    calls: int = 0

    async def split_tasks(self, *, prompt: str, today: date) -> SplitResult:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMFailedError("simulated LLM failure")
        tasks = self.responses.pop(0)
        intent = self.intents.pop(0) if self.intents else "plan"
        return SplitResult(intent=intent, tasks=tasks)
```

- [ ] **Step 8: 다른 fake/stub 갱신**

`tests/adapters/todo_creation/test_fake_llm.py`: split_tasks 결과 단언을 `.tasks` 로 수정(예: `out[0].title` → `out.tasks[0].title`, `len(out)` → `len(out.tasks)`, `out1`/`out2` 동일).

`tests/api/test_todo_generate.py` 의 `_FakeGenerateLLM`:
```python
from agents.todo_creation.schemas import SplitResult, TaskCandidate


class _FakeGenerateLLM:
    async def split_tasks(self, *, prompt, today):
        return SplitResult(
            intent="plan",
            tasks=[TaskCandidate(title="장보기", due_date=today, tags=[])],
        )
```
(기존 `from agents.todo_creation.schemas import TaskCandidate` 줄과 통합)

`tests/agents/todo_creation/planner/test_pipeline.py:65` 의 stub `async def split_tasks(self, *, prompt: str, today: date):` — 플래너는 split_tasks 를 호출하지 않으므로 본문이 `...`/`return None` 이면 그대로 둔다(미사용). 만약 `list` 를 반환하고 있으면 `SplitResult(intent="plan", tasks=[])` 로 교체.

- [ ] **Step 9: 전체 관련 스위트 통과 확인**

Run: `uv run pytest tests/adapters/todo_creation tests/agents/todo_creation/todo tests/api/test_todo_generate.py -q`
Expected: PASS (기존 동작 보존, 타입만 이동)

- [ ] **Step 10: Commit**

```bash
git add agents/todo_creation/protocols.py adapters/todo_creation/qwen_llm.py agents/todo_creation/todo/nodes/task_splitter.py tests/agents/todo_creation/fake_llm.py tests/adapters/todo_creation/test_qwen_llm.py tests/adapters/todo_creation/test_fake_llm.py tests/api/test_todo_generate.py tests/agents/todo_creation/planner/test_pipeline.py
git commit -m "refactor: split_tasks 반환타입을 SplitResult(intent+tasks)로 이동"
```

---

## Task 3: TASK_SPLITTER_SYSTEM 프롬프트에 intent 규칙 추가

**Files:**
- Modify: `adapters/todo_creation/_prompts.py`
- Test: `tests/adapters/todo_creation/test_prompts.py`

- [ ] **Step 1: 프롬프트 계약 실패 테스트** — `tests/adapters/todo_creation/test_prompts.py` 에 추가

```python
def test_task_splitter_prompt_declares_intent_and_out_of_scope() -> None:
    from adapters.todo_creation._prompts import TASK_SPLITTER_SYSTEM

    assert "intent" in TASK_SPLITTER_SYSTEM
    assert "out_of_scope" in TASK_SPLITTER_SYSTEM
    assert '"intent"' in TASK_SPLITTER_SYSTEM
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/adapters/todo_creation/test_prompts.py::test_task_splitter_prompt_declares_intent_and_out_of_scope -q`
Expected: FAIL

- [ ] **Step 3: 프롬프트 수정** — `adapters/todo_creation/_prompts.py` 의 `TASK_SPLITTER_SYSTEM`

`[절대 규칙]` 의 스키마 줄을 교체:
```
- 스키마는 정확히 {"intent": "plan"|"out_of_scope", "tasks": [{"title": str, "due_date": "YYYY-MM-DD", "tags": [str]}]} 이다.
```
`[절대 규칙]` 블록 끝에 intent 규칙 추가(기존 `- tasks 수는 1개 이상 20개 이하이다.` 줄은 삭제하고 아래로 흡수):
```
- intent 는 입력이 일정/TODO 로 나눌 수 있는 목표·할 일이면 "plan", 날씨·잡담·단순 지식 질의·감정 표현(예: "배고프다", "졸려")처럼 나눌 수 없으면 "out_of_scope" 이다.
- intent 가 "out_of_scope" 이면 tasks 는 빈 배열 [] 로 둔다.
- intent 가 "plan" 이면 tasks 는 1개 이상 20개 이하이다.
```
예시 3개의 출력 앞에 `"intent":"plan",` 추가, 예:
```
출력: {"intent":"plan","tasks":[{"title":"전처리 결과서 제출","due_date":"2026-06-04","tags":["업무"]},{"title":"운동가기","due_date":"2026-06-04","tags":["건강"]}]}
```
out_of_scope 예시 추가:
```
[예시 4]
입력: today=2026-06-04 / 배고프다
출력: {"intent":"out_of_scope","tasks":[]}
```

- [ ] **Step 4: 통과 + 프롬프트 계약 회귀 확인**

Run: `uv run pytest tests/adapters/todo_creation/test_prompts.py -q`
Expected: PASS (기존 "todos.content"/"schedules.title" 등 단언 유지)

- [ ] **Step 5: Commit**

```bash
git add adapters/todo_creation/_prompts.py tests/adapters/todo_creation/test_prompts.py
git commit -m "feat: task_splitter 프롬프트에 intent(out_of_scope) 규칙·예시 추가"
```

---

## Task 4: 단일 그래프 out_of_scope 분기 (node·state·pipeline)

**Files:**
- Modify: `agents/todo_creation/todo/state.py`
- Modify: `agents/todo_creation/todo/nodes/task_splitter.py`
- Create: `agents/todo_creation/todo/nodes/out_of_scope.py`
- Modify: `agents/todo_creation/todo/pipeline.py`
- Test: `tests/agents/todo_creation/todo/nodes/test_task_splitter.py`, `tests/agents/todo_creation/todo/test_pipeline.py`

- [ ] **Step 1: node 분기 실패 테스트** — `tests/agents/todo_creation/todo/nodes/test_task_splitter.py` 에 추가

```python
async def test_out_of_scope_sets_intent_and_no_split() -> None:
    llm = FakeLLM(responses=[[]], intents=["out_of_scope"])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff["intent"] == "out_of_scope"
    assert "split_tasks" not in diff
    assert llm.calls == 1  # out_of_scope 는 빈 tasks 라도 재시도하지 않는다


async def test_plan_intent_sets_split_tasks() -> None:
    llm = FakeLLM(responses=[[_t("코테")]], intents=["plan"])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff["intent"] == "plan"
    assert len(diff["split_tasks"]) == 1
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/agents/todo_creation/todo/nodes/test_task_splitter.py -q`
Expected: FAIL — `KeyError: 'intent'`

- [ ] **Step 3: state 에 intent 추가** — `agents/todo_creation/todo/state.py`

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from agents.todo_creation.schemas import (
    GenerateResult,
    OutOfScopeResult,
    TaskCandidate,
    TodoInput,
)


class GenerateGraphState(TypedDict, total=False):
    # required
    input: TodoInput
    now: datetime
    # produced
    intent: Literal["plan", "out_of_scope"] | None
    split_tasks: list[TaskCandidate] | None
    result: GenerateResult | OutOfScopeResult | None
    error: Exception | None
```

- [ ] **Step 4: task_splitter_node 에 out_of_scope 분기** — `agents/todo_creation/todo/nodes/task_splitter.py`

`task_splitter_node` 본문을 교체:
```python
async def task_splitter_node(
    state: GenerateGraphState, config: RunnableConfig
) -> dict[str, Any]:
    ports = get_ports(config)
    today = state["input"].today

    split = await ports.llm.split_tasks(prompt=state["input"].prompt, today=today)
    if split.intent == "out_of_scope":
        return {"intent": "out_of_scope"}

    raw = split.tasks
    if not raw:
        # B2: one retry on empty (plan 인데 비었을 때만)
        split = await ports.llm.split_tasks(prompt=state["input"].prompt, today=today)
        if split.intent == "out_of_scope":
            return {"intent": "out_of_scope"}
        raw = split.tasks
        if not raw:
            raise LLMOutputError("task_splitter returned empty list after retry")

    if len(raw) > MAX_TASKS:
        raise LLMOutputError(
            f"task_splitter returned {len(raw)} tasks (max {MAX_TASKS})"
        )

    corrected = [_correct(t, today) for t in raw]
    return {"intent": "plan", "split_tasks": corrected}
```

- [ ] **Step 5: out_of_scope 노드 생성** — `agents/todo_creation/todo/nodes/out_of_scope.py`

```python
from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.schemas import OUT_OF_SCOPE_MESSAGE, OutOfScopeResult
from agents.todo_creation.todo.state import GenerateGraphState


async def out_of_scope_node(
    state: GenerateGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """단일턴: 플랜과 무관한 입력에 고정 안내문(OutOfScopeResult)을 반환한다."""

    return {
        "result": OutOfScopeResult(thread_id="", message=OUT_OF_SCOPE_MESSAGE),
    }
```

- [ ] **Step 6: pipeline 그래프에 조건 분기** — `agents/todo_creation/todo/pipeline.py`

import 추가:
```python
from agents.todo_creation.todo.nodes.out_of_scope import out_of_scope_node
```
`build_generate_graph` 를 교체:
```python
def _route_after_split(state: GenerateGraphState) -> str:
    return "out_of_scope" if state.get("intent") == "out_of_scope" else "date_router"


def build_generate_graph():
    g = StateGraph(GenerateGraphState)

    g.add_node("validate", validate_node)
    g.add_node(
        "task_splitter",
        task_splitter_node,
        retry=RetryPolicy(max_attempts=3, retry_on=(LLMFailedError,)),
    )
    g.add_node("date_router", date_router_node)
    g.add_node("out_of_scope", out_of_scope_node)

    g.add_edge(START, "validate")
    g.add_edge("validate", "task_splitter")
    g.add_conditional_edges(
        "task_splitter", _route_after_split, ["date_router", "out_of_scope"]
    )
    g.add_edge("date_router", END)
    g.add_edge("out_of_scope", END)

    return g.compile()
```

- [ ] **Step 7: pipeline 통합 실패 테스트** — `tests/agents/todo_creation/todo/test_pipeline.py` 에 추가

```python
async def test_pipeline_returns_out_of_scope_result() -> None:
    from datetime import date, datetime
    from agents.todo_creation.schemas import OutOfScopeResult, TodoInput
    from agents.todo_creation.todo import pipeline as single_pipeline
    from agents.todo_creation.todo.pipeline import GeneratePorts
    from tests.agents.todo_creation.fake_llm import FakeLLM

    ports = GeneratePorts(llm=FakeLLM(responses=[[]], intents=["out_of_scope"]))
    result = await single_pipeline.run(
        TodoInput(user_id="u1", prompt="배고프다", today=date(2026, 6, 13)),
        ports=ports,
        now=datetime(2026, 6, 13, 9, 0),
    )
    assert isinstance(result, OutOfScopeResult)
    assert result.thread_id == ""
    assert result.message
```

> 기존 `test_pipeline.py` 의 plan 케이스(`GenerateResult` 반환)가 그대로 통과하는지도 확인. FakeLLM 호출 시 `intents` 미지정이면 기본 "plan" 이라 회귀 없음.

- [ ] **Step 8: 통과 확인**

Run: `uv run pytest tests/agents/todo_creation/todo -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add agents/todo_creation/todo/state.py agents/todo_creation/todo/nodes/task_splitter.py agents/todo_creation/todo/nodes/out_of_scope.py agents/todo_creation/todo/pipeline.py tests/agents/todo_creation/todo/nodes/test_task_splitter.py tests/agents/todo_creation/todo/test_pipeline.py
git commit -m "feat: 단일 generate 그래프에 out_of_scope 분기 추가"
```

---

## Task 5: API 응답모델을 SingleTurnResult 로

**Files:**
- Modify: `api/todo_creation/router.py`
- Test: `tests/api/test_todo_generate.py`

- [ ] **Step 1: API out_of_scope 실패 테스트** — `tests/api/test_todo_generate.py` 에 추가

```python
class _FakeOutOfScopeLLM:
    async def split_tasks(self, *, prompt, today):
        from agents.todo_creation.schemas import SplitResult

        return SplitResult(intent="out_of_scope", tasks=[])


def _override_oos():
    return GeneratePorts(llm=cast(LLMPort, _FakeOutOfScopeLLM()))


def test_generate_returns_out_of_scope(api_client):
    """플랜과 무관한 입력은 out_of_scope 봉투로 반환한다."""
    api_client.app.dependency_overrides[get_todo_generate_ports] = _override_oos
    body = {"user_id": "u1", "prompt": "배고프다", "today": "2026-06-13"}
    resp = api_client.post("/v1/todo/generate", json=body, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["result"]["kind"] == "out_of_scope"
    assert data["result"]["message"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/api/test_todo_generate.py::test_generate_returns_out_of_scope -q`
Expected: FAIL — 응답 검증 실패 또는 `kind` != out_of_scope (현재 response_model 이 GenerateResult 라 직렬화 오류)

- [ ] **Step 3: 라우터 응답모델 변경** — `api/todo_creation/router.py`

import 의 schemas 블록에 `SingleTurnResult` 추가:
```python
from agents.todo_creation.schemas import (
    CommitResult,
    FollowUpResult,
    GenerateResult,
    MultiGenerateInput,
    SingleTurnResult,
    TodoInput,
    TurnResult,
)
```
`_generate` 와 `generate` 의 반환·응답모델 타입 교체:
```python
async def _generate(
    body: TodoInput,
    ports: GeneratePorts,
) -> Envelope[SingleTurnResult]:
    result = await single_pipeline.run(body, ports=ports, now=datetime.now())
    return done(result)
```
```python
@router.post("/generate", response_model=Envelope[SingleTurnResult])
async def generate(
    body: TodoInput,
    ports: GeneratePorts = Depends(get_todo_generate_ports),
) -> Envelope[SingleTurnResult]:
    return await _generate(body, ports)
```
> `GenerateResult` 가 router 에서 직접 참조되지 않게 되면 unused import 경고가 날 수 있다. 내 변경이 만든 orphan 이면 import 목록에서 `GenerateResult` 제거(다른 unused 는 건드리지 않음).

- [ ] **Step 4: 통과 + 회귀 확인**

Run: `uv run pytest tests/api/test_todo_generate.py -q`
Expected: PASS (기존 `test_generate_returns_done_envelope`/`candidates` 케이스도 통과 — SingleTurnResult 가 GenerateResult 를 포함)

- [ ] **Step 5: Commit**

```bash
git add api/todo_creation/router.py tests/api/test_todo_generate.py
git commit -m "feat: /v1/todo/generate 응답모델을 SingleTurnResult로 (out_of_scope 지원)"
```

---

## Task 6: 전체 스위트 + 통합 확인 + 마무리

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 테스트 실행**

Run: `uv run pytest -q`
Expected: PASS, 커버리지 80%+ 유지

- [ ] **Step 2: 로컬 통합 수동 확인 (서버 재기동 후)**

서버 재시작:
```bash
.venv/bin/uvicorn api.main:app --port 8010
```
out_of_scope (실제 RunPod, 프롬프트 반영됨):
```bash
curl -s -X POST http://localhost:8010/v1/todo/generate \
  -H "X-API-Key: $(grep '^MONGLE_API_KEY=' .env | sed 's/^MONGLE_API_KEY=//')" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test-1","prompt":"배고프다","today":"2026-06-13"}'
```
Expected: `result.kind == "out_of_scope"`

회귀(TST-LLM-001):
```bash
curl -s -X POST http://localhost:8010/v1/todo/generate \
  -H "X-API-Key: $(grep '^MONGLE_API_KEY=' .env | sed 's/^MONGLE_API_KEY=//')" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test-1","prompt":"오늘 영어단어 30개 외우고, 토익 복습하고, 산책할 거야","today":"2026-06-13"}'
```
Expected: `result.kind == "candidates"`, `todos.length == 3`

> 참고: 프롬프트가 fine-tune 학습 형식과 다를 수 있어 모델이 intent 를 빠뜨릴 수 있다. 그 경우 파서가 "plan" 으로 폴백하므로 out_of_scope 가 안 나올 수 있다(무회귀이지만 기능 미작동). 이때는 spec §1 D3 한계로 기록하고, 디코딩/모델 측 후속(별도 백로그)으로 넘긴다.

- [ ] **Step 3: CHANGELOG 갱신** (프로젝트 관례 — `docs/FEATURES.md` §4 DoD)

`CHANGELOG.md` 상단에 항목 추가:
```
- todo: 단일 /v1/todo/generate 가 비-목표 입력을 out_of_scope 로 응답 (split intent 도입)
```

- [ ] **Step 4: 최종 Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG 단일 generate out_of_scope 항목"
```

---

## Self-Review 결과

- **Spec 커버리지:** D1(기존 호출에 intent, Task 2·3) / D2(스키마 확장, Task 3) / D3(intent 누락→plan, Task 2 parser·테스트) / D4(OutOfScopeResult·메시지 공유, Task 1·4) / D5(SingleTurnResult, Task 1·5) / D6(thread_id="", Task 4·5) / D7(범위 격리 — quest/planner/commit 미변경) — 전부 태스크에 매핑됨.
- **Placeholder:** 없음(모든 코드 스텝에 실제 코드 포함).
- **타입 일관성:** `SplitResult(intent, tasks)`·`SingleTurnResult`·`OUT_OF_SCOPE_MESSAGE` 가 정의(Task 1)→사용(Task 2·4·5) 동일 명칭. `split_tasks` 반환타입 SplitResult 가 프로토콜·어댑터·fake·node 에서 일치.
