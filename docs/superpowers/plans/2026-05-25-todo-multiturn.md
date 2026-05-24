# Multi-Turn TODO Chatbot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `agents/todo_creation/multi_turn/` 멀티턴 챗봇 LangGraph 파이프라인 구현 (정보수집=결정론적, 수정루프=tool-calling 하이브리드).

**Architecture:** Hybrid LangGraph 그래프. `validate → phase_router → (gathering: planner_judge → follow_up | plan_generator → tagger) | (reviewing: edit_agent → regenerate_plan | confirm) → present → END`. SessionStorePort 로 turn 간 상태 보관. commit/pipeline.run() 위임.

**Tech Stack:** Python 3.12, LangGraph 0.2+ (StateGraph, RetryPolicy), Pydantic v2, pytest, asyncio.

**Working directory:** `/Users/jpaper/Documents/projects/mongle-village-todo`
**Branch:** `feat/todo-multiturn` (이미 생성됨)
**Spec:** [`docs/superpowers/specs/2026-05-25-todo-multiturn-design.md`](../specs/2026-05-25-todo-multiturn-design.md)

---

## File Structure

**신규 (Create):**
- `agents/todo_creation/multi_turn/__init__.py`
- `agents/todo_creation/multi_turn/state.py`
- `agents/todo_creation/multi_turn/session_store.py`
- `agents/todo_creation/multi_turn/tools.py`
- `agents/todo_creation/multi_turn/graph.py`
- `agents/todo_creation/multi_turn/pipeline.py`
- `agents/todo_creation/multi_turn/nodes/__init__.py`
- `agents/todo_creation/multi_turn/nodes/{validate,phase_router,planner_judge,follow_up,plan_generator,tagger,edit_agent,commit_invoke,present}.py`
- `adapters/todo_creation/{fake_multi_turn_llm,openai_multi_turn}.py`
- `tests/agents/todo_creation/multi_turn/{__init__,conftest,test_session_store,test_graph,test_pipeline}.py`
- `tests/agents/todo_creation/multi_turn/nodes/{__init__,test_validate,test_phase_router,test_planner_judge,test_follow_up,test_plan_generator,test_tagger,test_edit_agent,test_commit_invoke,test_present}.py`
- `tests/adapters/todo_creation/test_openai_multi_turn.py`

**수정 (Modify):**
- `agents/todo_creation/schemas.py` — 신규 Pydantic 모델 11개
- `agents/todo_creation/protocols.py` — `MultiTurnLLMPort`, `SessionStorePort`
- `agents/todo_creation/exceptions.py` — `SessionStoreError`, `EditAgentError`
- `agents/todo_creation/debug.py` — `Kind` 에 `"multi_turn"` 추가
- `docs/features/todo/architecture.mmd` — MULTI 서브그래프 교체
- `docs/features/todo/CLAUDE.md` — §7 갱신
- `CHANGELOG.md` — Unreleased/Added

---

## Phase 1: Schemas (Foundation)

### Task 1.1: 새 Pydantic 모델 추가

**Files:**
- Modify: `agents/todo_creation/schemas.py`
- Test: `tests/agents/todo_creation/test_schemas.py`

- [ ] **Step 1: 테스트 작성** — `tests/agents/todo_creation/test_schemas.py` 파일 끝에 추가:

```python
# === multi_turn schemas ===
from datetime import date, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from agents.todo_creation.schemas import (
    AgentDecision, ChatMessage, Day, MultiTurnInput, ParsedGoal, PlanDraft,
    PlannerJudgment, SessionState, TaggedPlan, Task, TurnResult,
)


def test_multi_turn_input_max_length_600():
    inp = MultiTurnInput(user_id="u1", session_id="s1", message="가" * 600, today=date(2026, 5, 25))
    assert len(inp.message) == 600


def test_multi_turn_input_over_600_rejected():
    with pytest.raises(PydanticValidationError):
        MultiTurnInput(user_id="u1", session_id="s1", message="가" * 601, today=date(2026, 5, 25))


def test_chat_message_roles():
    assert ChatMessage(role="user", content="hi").role == "user"
    with pytest.raises(PydanticValidationError):
        ChatMessage(role="system", content="x")


def test_parsed_goal_all_optional():
    g = ParsedGoal()
    assert g.goal_type is None and g.extras == {}


def test_planner_judgment_round_trip():
    j = PlannerJudgment(is_sufficient=False, missing_aspects=["하루 시간"], parsed_goal=ParsedGoal(goal_type="정처기"))
    assert j.missing_aspects == ["하루 시간"]


def test_plan_draft_no_length_at_schema():
    draft = PlanDraft(summary_text="가" * 2000, days=[])
    assert len(draft.summary_text) == 2000


def test_tagged_plan_has_tags():
    plan = TaggedPlan(
        summary_text="요약",
        days=[Day(date=date(2026, 5, 25), tasks=[Task(title="공부", tags=["학습"])])],
    )
    assert plan.days[0].tasks[0].tags == ["학습"]


def test_agent_decision_tool_names():
    assert AgentDecision(tool_name="confirm", tool_args={}).tool_name == "confirm"
    d = AgentDecision(tool_name="regenerate_plan", tool_args={"instructions": "더 짧게"})
    assert d.tool_args["instructions"] == "더 짧게"
    with pytest.raises(PydanticValidationError):
        AgentDecision(tool_name="invalid", tool_args={})


def test_turn_result_kinds():
    assert TurnResult(kind="question", question="?").kind == "question"
    assert TurnResult(kind="plan", plan=TaggedPlan(summary_text="x", days=[])).plan is not None
    assert TurnResult(kind="committed").kind == "committed"


def test_session_state_phase_literals():
    now = datetime(2026, 5, 25, 12, 0)
    s = SessionState(session_id="s1", user_id="u1", phase="gathering", history=[], parsed_goal=None, current_plan=None, created_at=now, updated_at=now)
    assert s.phase == "gathering"
    with pytest.raises(PydanticValidationError):
        SessionState(session_id="s1", user_id="u1", phase="invalid", history=[], parsed_goal=None, current_plan=None, created_at=now, updated_at=now)
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd /Users/jpaper/Documents/projects/mongle-village-todo && uv run pytest tests/agents/todo_creation/test_schemas.py -v 2>&1 | tail -20
```

Expected: ImportError (새 심볼들이 schemas.py 에 없음)

- [ ] **Step 3: 스키마 추가 구현** — `agents/todo_creation/schemas.py` 파일 끝에 추가:

```python
from datetime import datetime
from typing import Literal


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1)]


class ParsedGoal(BaseModel):
    goal_type: str | None = None
    deadline: date | None = None
    daily_capacity: str | None = None
    target_level: str | None = None
    extras: Annotated[dict[str, str], Field(default_factory=dict)]


class PlannerJudgment(BaseModel):
    is_sufficient: bool
    missing_aspects: Annotated[list[str], Field(default_factory=list)]
    parsed_goal: ParsedGoal


class Task(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=80)]
    detail: str | None = None
    time_hint: str | None = None
    tags: Annotated[list[str], Field(default_factory=list)]


class Day(BaseModel):
    date: date
    tasks: Annotated[list[Task], Field(default_factory=list)]


class PlanDraft(BaseModel):
    summary_text: Annotated[str, Field(min_length=1)]
    days: Annotated[list[Day], Field(default_factory=list)]


class TaggedPlan(BaseModel):
    summary_text: Annotated[str, Field(min_length=1)]
    days: Annotated[list[Day], Field(default_factory=list)]


class MultiTurnInput(BaseModel):
    user_id: Annotated[str, Field(min_length=1)]
    session_id: Annotated[str, Field(min_length=1)]
    message: Annotated[str, Field(min_length=1, max_length=600)]
    today: date


class AgentDecision(BaseModel):
    tool_name: Literal["regenerate_plan", "confirm"]
    tool_args: Annotated[dict[str, str], Field(default_factory=dict)]


class TurnResult(BaseModel):
    kind: Literal["question", "plan", "committed"]
    question: str | None = None
    plan: TaggedPlan | None = None
    commit_result: CommitResult | None = None


class SessionState(BaseModel):
    session_id: Annotated[str, Field(min_length=1)]
    user_id: Annotated[str, Field(min_length=1)]
    phase: Literal["gathering", "reviewing"]
    history: Annotated[list[ChatMessage], Field(default_factory=list)]
    parsed_goal: ParsedGoal | None = None
    current_plan: TaggedPlan | None = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/agents/todo_creation/test_schemas.py -v 2>&1 | tail -20
```

Expected: 모든 신규 테스트 + 기존 테스트 PASS

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/schemas.py tests/agents/todo_creation/test_schemas.py
git commit -m "feat(todo): multi_turn schemas (Pydantic 모델 11개 추가)"
```

---

## Phase 2: Protocols & Exceptions

### Task 2.1: Protocol + Exception 추가

**Files:**
- Modify: `agents/todo_creation/protocols.py`
- Modify: `agents/todo_creation/exceptions.py`

- [ ] **Step 1: exceptions 추가** — `agents/todo_creation/exceptions.py` 끝에 추가:

```python
class SessionStoreError(TodoCreationError):
    pass


class EditAgentError(TodoCreationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
```

- [ ] **Step 2: protocols 추가** — `agents/todo_creation/protocols.py` 끝에 추가 (필요한 import 도 함께):

```python
from agents.todo_creation.schemas import (
    AgentDecision, ChatMessage, ParsedGoal, PlanDraft, PlannerJudgment,
    SessionState, TaggedPlan,
)


class MultiTurnLLMPort(Protocol):
    async def judge_planner(self, *, history: list[ChatMessage], previous_goal: ParsedGoal | None, today: date) -> PlannerJudgment: ...
    async def generate_follow_up(self, *, missing_aspects: list[str], history: list[ChatMessage]) -> str: ...
    async def generate_plan(self, *, parsed_goal: ParsedGoal, today: date, edit_instructions: str | None) -> PlanDraft: ...
    async def tag_plan(self, *, plan_draft: PlanDraft, parsed_goal: ParsedGoal) -> TaggedPlan: ...
    async def edit_agent_step(self, *, history: list[ChatMessage], current_plan: TaggedPlan) -> AgentDecision: ...


class SessionStorePort(Protocol):
    async def load(self, *, session_id: str) -> SessionState | None: ...
    async def save(self, *, state: SessionState) -> None: ...
    async def delete(self, *, session_id: str) -> None: ...
```

- [ ] **Step 3: import 검증**

```bash
uv run python -c "
from agents.todo_creation.protocols import MultiTurnLLMPort, SessionStorePort
from agents.todo_creation.exceptions import SessionStoreError, EditAgentError
print('OK')
"
```

Expected: `OK`

- [ ] **Step 4: 커밋**

```bash
git add agents/todo_creation/protocols.py agents/todo_creation/exceptions.py
git commit -m "feat(todo): MultiTurnLLMPort + SessionStorePort + 신규 예외"
```

---

## Phase 3: Session Store

### Task 3.1: InMemorySessionStore + 테스트

**Files:**
- Create: `agents/todo_creation/multi_turn/{__init__.py,session_store.py}`, `agents/todo_creation/multi_turn/nodes/__init__.py`
- Create: `tests/agents/todo_creation/multi_turn/{__init__.py,test_session_store.py}`, `tests/agents/todo_creation/multi_turn/nodes/__init__.py`

- [ ] **Step 1: 빈 패키지 마커 생성**

```bash
cd /Users/jpaper/Documents/projects/mongle-village-todo
mkdir -p agents/todo_creation/multi_turn/nodes tests/agents/todo_creation/multi_turn/nodes
touch agents/todo_creation/multi_turn/__init__.py \
      agents/todo_creation/multi_turn/nodes/__init__.py \
      tests/agents/todo_creation/multi_turn/__init__.py \
      tests/agents/todo_creation/multi_turn/nodes/__init__.py
```

- [ ] **Step 2: 테스트 작성** — `tests/agents/todo_creation/multi_turn/test_session_store.py`:

```python
from __future__ import annotations

from datetime import datetime

import pytest

from agents.todo_creation.multi_turn.session_store import InMemorySessionStore
from agents.todo_creation.schemas import SessionState


def _state(session_id: str = "s1") -> SessionState:
    now = datetime(2026, 5, 25, 12, 0)
    return SessionState(
        session_id=session_id, user_id="u1", phase="gathering", history=[],
        parsed_goal=None, current_plan=None, created_at=now, updated_at=now,
    )


@pytest.mark.asyncio
async def test_load_returns_none_when_missing():
    store = InMemorySessionStore()
    assert await store.load(session_id="nope") is None


@pytest.mark.asyncio
async def test_save_then_load_roundtrip():
    store = InMemorySessionStore()
    await store.save(state=_state())
    loaded = await store.load(session_id="s1")
    assert loaded is not None and loaded.phase == "gathering"


@pytest.mark.asyncio
async def test_save_is_upsert():
    store = InMemorySessionStore()
    s = _state()
    await store.save(state=s)
    await store.save(state=s.model_copy(update={"phase": "reviewing"}))
    loaded = await store.load(session_id="s1")
    assert loaded.phase == "reviewing"


@pytest.mark.asyncio
async def test_delete_removes():
    store = InMemorySessionStore()
    await store.save(state=_state())
    await store.delete(session_id="s1")
    assert await store.load(session_id="s1") is None


@pytest.mark.asyncio
async def test_delete_missing_is_idempotent():
    store = InMemorySessionStore()
    await store.delete(session_id="nope")
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/test_session_store.py -v 2>&1 | tail -20
```

Expected: ImportError

- [ ] **Step 4: 구현 작성** — `agents/todo_creation/multi_turn/session_store.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from agents.todo_creation.schemas import SessionState


@dataclass
class InMemorySessionStore:
    """In-memory SessionStorePort implementation for tests/dev. Single asyncio.Lock."""

    _by_id: dict[str, SessionState] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def load(self, *, session_id: str) -> SessionState | None:
        async with self._lock:
            return self._by_id.get(session_id)

    async def save(self, *, state: SessionState) -> None:
        async with self._lock:
            self._by_id[state.session_id] = state

    async def delete(self, *, session_id: str) -> None:
        async with self._lock:
            self._by_id.pop(session_id, None)
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/test_session_store.py -v 2>&1 | tail -10
```

Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add agents/todo_creation/multi_turn/__init__.py \
        agents/todo_creation/multi_turn/nodes/__init__.py \
        agents/todo_creation/multi_turn/session_store.py \
        tests/agents/todo_creation/multi_turn/__init__.py \
        tests/agents/todo_creation/multi_turn/nodes/__init__.py \
        tests/agents/todo_creation/multi_turn/test_session_store.py
git commit -m "feat(todo): InMemorySessionStore + 단위 테스트"
```

---

## Phase 4: FakeMultiTurnLLM + Conftest

### Task 4.1: FakeMultiTurnLLM

**Files:**
- Create: `adapters/todo_creation/fake_multi_turn_llm.py`

- [ ] **Step 1: 구현 작성** — `adapters/todo_creation/fake_multi_turn_llm.py`:

```python
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.schemas import (
    AgentDecision, ChatMessage, ParsedGoal, PlanDraft, PlannerJudgment, TaggedPlan,
)


@dataclass
class FakeMultiTurnLLM:
    """Scripted MultiTurnLLMPort for tests.

    Response lists are FIFO queues. `fail_times_<method>` raises LLMFailedError
    that many times before any response is popped.
    """

    judge_responses: list[PlannerJudgment] = field(default_factory=list)
    follow_up_responses: list[str] = field(default_factory=list)
    plan_responses: list[PlanDraft] = field(default_factory=list)
    tag_responses: list[TaggedPlan] = field(default_factory=list)
    agent_decisions: list[AgentDecision] = field(default_factory=list)

    fail_times_judge: int = 0
    fail_times_follow_up: int = 0
    fail_times_plan: int = 0
    fail_times_tag: int = 0
    fail_times_agent: int = 0

    calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_plan_edit_instructions: list[str | None] = field(default_factory=list)

    async def judge_planner(self, *, history, previous_goal, today) -> PlannerJudgment:
        self.calls["judge_planner"] += 1
        if self.fail_times_judge > 0:
            self.fail_times_judge -= 1
            raise LLMFailedError("simulated judge failure")
        assert self.judge_responses, "unexpected judge_planner call"
        return self.judge_responses.pop(0)

    async def generate_follow_up(self, *, missing_aspects, history) -> str:
        self.calls["generate_follow_up"] += 1
        if self.fail_times_follow_up > 0:
            self.fail_times_follow_up -= 1
            raise LLMFailedError("simulated follow_up failure")
        assert self.follow_up_responses, "unexpected generate_follow_up call"
        return self.follow_up_responses.pop(0)

    async def generate_plan(self, *, parsed_goal, today, edit_instructions) -> PlanDraft:
        self.calls["generate_plan"] += 1
        self.last_plan_edit_instructions.append(edit_instructions)
        if self.fail_times_plan > 0:
            self.fail_times_plan -= 1
            raise LLMFailedError("simulated plan failure")
        assert self.plan_responses, "unexpected generate_plan call"
        return self.plan_responses.pop(0)

    async def tag_plan(self, *, plan_draft, parsed_goal) -> TaggedPlan:
        self.calls["tag_plan"] += 1
        if self.fail_times_tag > 0:
            self.fail_times_tag -= 1
            raise LLMFailedError("simulated tag failure")
        assert self.tag_responses, "unexpected tag_plan call"
        return self.tag_responses.pop(0)

    async def edit_agent_step(self, *, history, current_plan) -> AgentDecision:
        self.calls["edit_agent_step"] += 1
        if self.fail_times_agent > 0:
            self.fail_times_agent -= 1
            raise LLMFailedError("simulated agent failure")
        assert self.agent_decisions, "unexpected edit_agent_step call"
        return self.agent_decisions.pop(0)
```

- [ ] **Step 2: import 검증**

```bash
uv run python -c "from adapters.todo_creation.fake_multi_turn_llm import FakeMultiTurnLLM; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
git add adapters/todo_creation/fake_multi_turn_llm.py
git commit -m "feat(todo): FakeMultiTurnLLM 어댑터 (큐 기반 스크립트 LLM)"
```

### Task 4.2: conftest.py

**Files:**
- Create: `tests/agents/todo_creation/multi_turn/conftest.py`

- [ ] **Step 1: conftest 작성**:

```python
from __future__ import annotations

from datetime import date, datetime

import pytest

from adapters.todo_creation.fake_multi_turn_llm import FakeMultiTurnLLM
from agents.todo_creation.multi_turn.session_store import InMemorySessionStore
from agents.todo_creation.schemas import MultiTurnInput


@pytest.fixture
def today() -> date:
    return date(2026, 5, 25)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 25, 12, 0, 0)


@pytest.fixture
def fake_mt_llm() -> FakeMultiTurnLLM:
    return FakeMultiTurnLLM()


@pytest.fixture
def session_store() -> InMemorySessionStore:
    return InMemorySessionStore()


@pytest.fixture
def base_input(today) -> MultiTurnInput:
    return MultiTurnInput(user_id="u1", session_id="s1", message="3일 후 정보처리기사 시험", today=today)
```

- [ ] **Step 2: collection 검증**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/test_session_store.py --collect-only 2>&1 | tail -10
```

Expected: collection 정상

- [ ] **Step 3: 커밋**

```bash
git add tests/agents/todo_creation/multi_turn/conftest.py
git commit -m "test(todo): multi_turn conftest fixtures"
```

---

## Phase 5: Validate Node

### Task 5.1: validate_node + state

**Files:**
- Create: `agents/todo_creation/multi_turn/state.py`
- Create: `agents/todo_creation/multi_turn/nodes/validate.py`
- Create: `tests/agents/todo_creation/multi_turn/nodes/test_validate.py`

- [ ] **Step 1: state 정의** — `agents/todo_creation/multi_turn/state.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from agents.todo_creation.schemas import (
    ChatMessage, MultiTurnInput, ParsedGoal, PlanDraft, PlannerJudgment, TaggedPlan, TurnResult,
)


class MultiTurnGraphState(TypedDict, total=False):
    input: MultiTurnInput
    now: datetime

    phase: Literal["gathering", "reviewing"]
    history: list[ChatMessage]
    parsed_goal: ParsedGoal | None
    current_plan: TaggedPlan | None

    judgment: PlannerJudgment | None
    follow_up_question: str | None

    edit_instructions: str | None
    confirmed: bool | None

    plan_draft: PlanDraft | None

    result: TurnResult | None
    error: Exception | None
```

- [ ] **Step 2: 테스트 작성** — `tests/agents/todo_creation/multi_turn/nodes/test_validate.py`:

```python
from __future__ import annotations

import pytest

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.multi_turn.nodes.validate import HANGUL_RATIO_MIN, validate_node


@pytest.mark.asyncio
async def test_validate_passes_normal_korean(base_input):
    assert await validate_node({"input": base_input}, {}) == {}


@pytest.mark.asyncio
async def test_m2_whitespace_only(base_input):
    state = {"input": base_input.model_copy(update={"message": "   "})}
    with pytest.raises(ValidationError) as ei:
        await validate_node(state, {})
    assert ei.value.code == "M2"


@pytest.mark.asyncio
async def test_m3_hangul_ratio_too_low(base_input):
    state = {"input": base_input.model_copy(update={"message": "abcdefghij"})}
    with pytest.raises(ValidationError) as ei:
        await validate_node(state, {})
    assert ei.value.code == "M3"


@pytest.mark.asyncio
async def test_m3_passes_mixed_korean_above_threshold(base_input):
    state = {"input": base_input.model_copy(update={"message": "한국어 a"})}
    assert await validate_node(state, {}) == {}


def test_hangul_ratio_constant():
    assert HANGUL_RATIO_MIN == 0.3
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_validate.py -v 2>&1 | tail -15
```

Expected: ImportError

- [ ] **Step 4: 구현 작성** — `agents/todo_creation/multi_turn/nodes/validate.py`:

```python
from __future__ import annotations

import re
from typing import Any

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.schemas import MultiTurnInput

HANGUL_RATIO_MIN = 0.3

_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def _hangul_ratio(text: str) -> float:
    stripped = re.sub(r"\s", "", text)
    if not stripped:
        return 0.0
    return len(_HANGUL_RE.findall(stripped)) / len(stripped)


def check(input: MultiTurnInput) -> None:
    if len(input.message) > 600:
        raise ValidationError(code="M1", message="message exceeds 600 chars")
    if not input.message.strip():
        raise ValidationError(code="M2", message="message is empty or whitespace")
    if _hangul_ratio(input.message) < HANGUL_RATIO_MIN:
        raise ValidationError(code="M3", message="message must be mostly Korean")


async def validate_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    check(state["input"])
    return {}
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_validate.py -v 2>&1 | tail -10
```

Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add agents/todo_creation/multi_turn/state.py \
        agents/todo_creation/multi_turn/nodes/validate.py \
        tests/agents/todo_creation/multi_turn/nodes/test_validate.py
git commit -m "feat(todo): multi_turn validate 노드 + state TypedDict"
```

---

## Phase 6: Phase Router

### Task 6.1: phase_router_node

**Files:**
- Create: `agents/todo_creation/multi_turn/nodes/phase_router.py`
- Create: `tests/agents/todo_creation/multi_turn/nodes/test_phase_router.py`

- [ ] **Step 1: 테스트 작성**:

```python
from __future__ import annotations

from datetime import datetime

import pytest

from agents.todo_creation.multi_turn.nodes.phase_router import (
    phase_router_node, route_after_phase_router,
)
from agents.todo_creation.schemas import ChatMessage, ParsedGoal, SessionState


class _Ports:
    def __init__(self, session_store):
        self.session_store = session_store


def _config(session_store):
    return {"configurable": {"ports": _Ports(session_store=session_store)}}


@pytest.mark.asyncio
async def test_new_session_starts_gathering(base_input, session_store):
    out = await phase_router_node({"input": base_input}, _config(session_store))
    assert out["phase"] == "gathering"
    assert out["parsed_goal"] is None and out["current_plan"] is None
    assert len(out["history"]) == 1 and out["history"][0].role == "user"


@pytest.mark.asyncio
async def test_existing_gathering_session_loads(base_input, session_store):
    now = datetime(2026, 5, 25, 11, 0)
    await session_store.save(state=SessionState(
        session_id=base_input.session_id, user_id=base_input.user_id, phase="gathering",
        history=[ChatMessage(role="user", content="이전")], parsed_goal=ParsedGoal(goal_type="X"),
        current_plan=None, created_at=now, updated_at=now,
    ))
    out = await phase_router_node({"input": base_input}, _config(session_store))
    assert out["phase"] == "gathering"
    assert out["parsed_goal"].goal_type == "X"
    assert len(out["history"]) == 2


@pytest.mark.asyncio
async def test_reviewing_session_loads(base_input, session_store):
    now = datetime(2026, 5, 25, 11, 0)
    await session_store.save(state=SessionState(
        session_id=base_input.session_id, user_id=base_input.user_id, phase="reviewing",
        history=[], parsed_goal=ParsedGoal(), current_plan=None,
        created_at=now, updated_at=now,
    ))
    out = await phase_router_node({"input": base_input}, _config(session_store))
    assert out["phase"] == "reviewing"


def test_route_after_phase_router():
    assert route_after_phase_router({"phase": "gathering"}) == "planner_judge"
    assert route_after_phase_router({"phase": "reviewing"}) == "edit_agent"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_phase_router.py -v 2>&1 | tail -15
```

Expected: ImportError

- [ ] **Step 3: 구현 작성** — `agents/todo_creation/multi_turn/nodes/phase_router.py`:

```python
from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.schemas import ChatMessage


async def phase_router_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    input_ = state["input"]
    loaded = await ports.session_store.load(session_id=input_.session_id)

    if loaded is None:
        phase = "gathering"
        history: list[ChatMessage] = []
        parsed_goal = None
        current_plan = None
    else:
        phase = loaded.phase
        history = list(loaded.history)
        parsed_goal = loaded.parsed_goal
        current_plan = loaded.current_plan

    history.append(ChatMessage(role="user", content=input_.message))
    return {"phase": phase, "history": history, "parsed_goal": parsed_goal, "current_plan": current_plan}


def route_after_phase_router(state: MultiTurnGraphState) -> str:
    return "planner_judge" if state["phase"] == "gathering" else "edit_agent"
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_phase_router.py -v 2>&1 | tail -10
```

Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/multi_turn/nodes/phase_router.py \
        tests/agents/todo_creation/multi_turn/nodes/test_phase_router.py
git commit -m "feat(todo): phase_router 노드 (gathering vs reviewing 분기)"
```

---

## Phase 7: Planner Judge & Follow-up

### Task 7.1: planner_judge_node

**Files:**
- Create: `agents/todo_creation/multi_turn/nodes/planner_judge.py`
- Create: `tests/agents/todo_creation/multi_turn/nodes/test_planner_judge.py`

- [ ] **Step 1: 테스트 작성**:

```python
from __future__ import annotations

import pytest

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.multi_turn.nodes.planner_judge import (
    planner_judge_node, route_after_judge,
)
from agents.todo_creation.schemas import ChatMessage, ParsedGoal, PlannerJudgment


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


@pytest.mark.asyncio
async def test_judge_returns_insufficient(base_input, fake_mt_llm):
    fake_mt_llm.judge_responses = [PlannerJudgment(
        is_sufficient=False, missing_aspects=["하루 시간"], parsed_goal=ParsedGoal(goal_type="정처기"),
    )]
    state = {"input": base_input, "history": [ChatMessage(role="user", content=base_input.message)], "parsed_goal": None}
    out = await planner_judge_node(state, _config(fake_mt_llm))
    assert out["judgment"].is_sufficient is False
    assert out["parsed_goal"].goal_type == "정처기"
    assert fake_mt_llm.calls["judge_planner"] == 1


@pytest.mark.asyncio
async def test_judge_returns_sufficient(base_input, fake_mt_llm):
    fake_mt_llm.judge_responses = [PlannerJudgment(
        is_sufficient=True, missing_aspects=[],
        parsed_goal=ParsedGoal(goal_type="정처기", daily_capacity="3h"),
    )]
    state = {"input": base_input, "history": [], "parsed_goal": ParsedGoal(goal_type="정처기")}
    out = await planner_judge_node(state, _config(fake_mt_llm))
    assert out["judgment"].is_sufficient is True
    assert out["parsed_goal"].daily_capacity == "3h"


@pytest.mark.asyncio
async def test_judge_raises_on_llm_failure(base_input, fake_mt_llm):
    fake_mt_llm.fail_times_judge = 1
    state = {"input": base_input, "history": [], "parsed_goal": None}
    with pytest.raises(LLMFailedError):
        await planner_judge_node(state, _config(fake_mt_llm))


def test_route_after_judge():
    yes = PlannerJudgment(is_sufficient=True, missing_aspects=[], parsed_goal=ParsedGoal())
    no = PlannerJudgment(is_sufficient=False, missing_aspects=["x"], parsed_goal=ParsedGoal())
    assert route_after_judge({"judgment": yes}) == "plan_generator"
    assert route_after_judge({"judgment": no}) == "follow_up"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_planner_judge.py -v 2>&1 | tail -15
```

Expected: ImportError

- [ ] **Step 3: 구현 작성** — `agents/todo_creation/multi_turn/nodes/planner_judge.py`:

```python
from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState


async def planner_judge_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    judgment = await ports.llm.judge_planner(
        history=state["history"],
        previous_goal=state.get("parsed_goal"),
        today=state["input"].today,
    )
    return {"judgment": judgment, "parsed_goal": judgment.parsed_goal}


def route_after_judge(state: MultiTurnGraphState) -> str:
    return "plan_generator" if state["judgment"].is_sufficient else "follow_up"
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_planner_judge.py -v 2>&1 | tail -10
```

Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/multi_turn/nodes/planner_judge.py \
        tests/agents/todo_creation/multi_turn/nodes/test_planner_judge.py
git commit -m "feat(todo): planner_judge 노드 (충분성 판정 + parsed_goal 갱신)"
```

### Task 7.2: follow_up_node

**Files:**
- Create: `agents/todo_creation/multi_turn/nodes/follow_up.py`
- Create: `tests/agents/todo_creation/multi_turn/nodes/test_follow_up.py`

- [ ] **Step 1: 테스트 작성**:

```python
from __future__ import annotations

import pytest

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.multi_turn.nodes.follow_up import follow_up_node
from agents.todo_creation.schemas import ChatMessage, ParsedGoal, PlannerJudgment


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


@pytest.mark.asyncio
async def test_follow_up_returns_question(base_input, fake_mt_llm):
    fake_mt_llm.follow_up_responses = ["하루에 몇 시간 정도 가능하실까요?"]
    state = {
        "input": base_input,
        "history": [ChatMessage(role="user", content=base_input.message)],
        "judgment": PlannerJudgment(is_sufficient=False, missing_aspects=["하루 시간"], parsed_goal=ParsedGoal()),
    }
    out = await follow_up_node(state, _config(fake_mt_llm))
    assert out["follow_up_question"] == "하루에 몇 시간 정도 가능하실까요?"


@pytest.mark.asyncio
async def test_follow_up_raises_on_llm_failure(base_input, fake_mt_llm):
    fake_mt_llm.fail_times_follow_up = 1
    state = {
        "input": base_input, "history": [],
        "judgment": PlannerJudgment(is_sufficient=False, missing_aspects=["x"], parsed_goal=ParsedGoal()),
    }
    with pytest.raises(LLMFailedError):
        await follow_up_node(state, _config(fake_mt_llm))
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_follow_up.py -v 2>&1 | tail -10
```

Expected: ImportError

- [ ] **Step 3: 구현 작성** — `agents/todo_creation/multi_turn/nodes/follow_up.py`:

```python
from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState


async def follow_up_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    question = await ports.llm.generate_follow_up(
        missing_aspects=state["judgment"].missing_aspects,
        history=state["history"],
    )
    return {"follow_up_question": question}
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_follow_up.py -v 2>&1 | tail -10
```

Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/multi_turn/nodes/follow_up.py \
        tests/agents/todo_creation/multi_turn/nodes/test_follow_up.py
git commit -m "feat(todo): follow_up 노드 (꼬리 질문 생성)"
```

---

## Phase 8: Plan Generator (C3 핸들링)

### Task 8.1: plan_generator_node

**Files:**
- Create: `agents/todo_creation/multi_turn/nodes/plan_generator.py`
- Create: `tests/agents/todo_creation/multi_turn/nodes/test_plan_generator.py`

- [ ] **Step 1: 테스트 작성**:

```python
from __future__ import annotations

from datetime import date

import pytest

from agents.todo_creation.multi_turn.nodes.plan_generator import (
    C3_LIMIT, plan_generator_node, truncate_at_sentence,
)
from agents.todo_creation.schemas import Day, ParsedGoal, PlanDraft, Task


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


def _draft(summary: str) -> PlanDraft:
    return PlanDraft(summary_text=summary, days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부")])])


@pytest.mark.asyncio
async def test_plan_generator_happy_path(base_input, fake_mt_llm):
    fake_mt_llm.plan_responses = [_draft("짧은 요약.")]
    state = {"input": base_input, "parsed_goal": ParsedGoal(goal_type="정처기")}
    out = await plan_generator_node(state, _config(fake_mt_llm))
    assert out["plan_draft"].summary_text == "짧은 요약."
    assert fake_mt_llm.last_plan_edit_instructions == [None]


@pytest.mark.asyncio
async def test_plan_generator_uses_edit_instructions(base_input, fake_mt_llm):
    fake_mt_llm.plan_responses = [_draft("수정된 요약.")]
    state = {"input": base_input, "parsed_goal": ParsedGoal(goal_type="정처기"), "edit_instructions": "마지막 날을 가볍게"}
    await plan_generator_node(state, _config(fake_mt_llm))
    assert fake_mt_llm.last_plan_edit_instructions == ["마지막 날을 가볍게"]


@pytest.mark.asyncio
async def test_plan_generator_c3_regenerates_once(base_input, fake_mt_llm):
    long_summary = "가" * (C3_LIMIT + 100)
    fake_mt_llm.plan_responses = [_draft(long_summary), _draft("이번엔 짧음.")]
    state = {"input": base_input, "parsed_goal": ParsedGoal(goal_type="정처기")}
    out = await plan_generator_node(state, _config(fake_mt_llm))
    assert out["plan_draft"].summary_text == "이번엔 짧음."
    assert fake_mt_llm.calls["generate_plan"] == 2


@pytest.mark.asyncio
async def test_plan_generator_c3_truncates_after_retry(base_input, fake_mt_llm):
    too_long = "첫 문장입니다. 두 번째 문장입니다. " + ("가" * (C3_LIMIT + 100))
    fake_mt_llm.plan_responses = [_draft(too_long), _draft(too_long)]
    state = {"input": base_input, "parsed_goal": ParsedGoal(goal_type="정처기")}
    out = await plan_generator_node(state, _config(fake_mt_llm))
    assert len(out["plan_draft"].summary_text) <= C3_LIMIT
    assert out["plan_draft"].summary_text.endswith(".")


def test_truncate_at_sentence_uses_last_period():
    text = "첫 문장. 두 번째 문장. 세 번째 문장입니다."
    out = truncate_at_sentence(text, limit=20)
    assert out.endswith(".") and len(out) <= 20


def test_truncate_at_sentence_hard_cut_when_no_period():
    text = "마침표가 전혀 없는 매우 긴 문장입니다 마침표 없음"
    out = truncate_at_sentence(text, limit=10)
    assert len(out) == 10
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_plan_generator.py -v 2>&1 | tail -15
```

Expected: ImportError

- [ ] **Step 3: 구현 작성** — `agents/todo_creation/multi_turn/nodes/plan_generator.py`:

```python
from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState

C3_LIMIT = 1500


def truncate_at_sentence(text: str, *, limit: int = C3_LIMIT) -> str:
    """Truncate text to <= limit chars, preferring the last sentence boundary."""
    if len(text) <= limit:
        return text
    candidate = text[:limit]
    last_period = candidate.rfind(".")
    if last_period >= 0:
        return candidate[: last_period + 1]
    return candidate


async def plan_generator_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    parsed_goal = state["parsed_goal"]
    today = state["input"].today
    edit_instructions = state.get("edit_instructions")

    draft = await ports.llm.generate_plan(
        parsed_goal=parsed_goal, today=today, edit_instructions=edit_instructions,
    )

    if len(draft.summary_text) > C3_LIMIT:
        retry_instructions = (
            (edit_instructions or "")
            + f"\n[중요] summary_text 는 반드시 {C3_LIMIT}자 이하."
        ).strip()
        draft = await ports.llm.generate_plan(
            parsed_goal=parsed_goal, today=today, edit_instructions=retry_instructions,
        )
        if len(draft.summary_text) > C3_LIMIT:
            draft = draft.model_copy(update={"summary_text": truncate_at_sentence(draft.summary_text)})

    return {"plan_draft": draft, "edit_instructions": None}
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_plan_generator.py -v 2>&1 | tail -10
```

Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/multi_turn/nodes/plan_generator.py \
        tests/agents/todo_creation/multi_turn/nodes/test_plan_generator.py
git commit -m "feat(todo): plan_generator 노드 (C3 재생성 + truncate fallback)"
```

---

## Phase 9: Tagger

### Task 9.1: tagger_node

**Files:**
- Create: `agents/todo_creation/multi_turn/nodes/tagger.py`
- Create: `tests/agents/todo_creation/multi_turn/nodes/test_tagger.py`

- [ ] **Step 1: 테스트 작성**:

```python
from __future__ import annotations

from datetime import date

import pytest

from agents.todo_creation.multi_turn.nodes.tagger import tagger_node
from agents.todo_creation.schemas import Day, ParsedGoal, PlanDraft, TaggedPlan, Task


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


@pytest.mark.asyncio
async def test_tagger_returns_tagged_plan(base_input, fake_mt_llm):
    fake_mt_llm.tag_responses = [TaggedPlan(
        summary_text="요약",
        days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부", tags=["학습", "정처기"])])],
    )]
    state = {
        "input": base_input,
        "plan_draft": PlanDraft(summary_text="요약", days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부")])]),
        "parsed_goal": ParsedGoal(goal_type="정처기"),
    }
    out = await tagger_node(state, _config(fake_mt_llm))
    assert out["current_plan"].days[0].tasks[0].tags == ["학습", "정처기"]
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_tagger.py -v 2>&1 | tail -10
```

Expected: ImportError

- [ ] **Step 3: 구현 작성** — `agents/todo_creation/multi_turn/nodes/tagger.py`:

```python
from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState


async def tagger_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    tagged = await ports.llm.tag_plan(
        plan_draft=state["plan_draft"], parsed_goal=state["parsed_goal"],
    )
    return {"current_plan": tagged}
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_tagger.py -v 2>&1 | tail -10
```

Expected: 1 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/multi_turn/nodes/tagger.py \
        tests/agents/todo_creation/multi_turn/nodes/test_tagger.py
git commit -m "feat(todo): tagger 노드 (자유 형식 태그 부여)"
```

---

## Phase 10: Edit Agent

### Task 10.1: edit_agent_node + tools.py

**Files:**
- Create: `agents/todo_creation/multi_turn/tools.py`
- Create: `agents/todo_creation/multi_turn/nodes/edit_agent.py`
- Create: `tests/agents/todo_creation/multi_turn/nodes/test_edit_agent.py`

- [ ] **Step 1: tools.py 작성** — `agents/todo_creation/multi_turn/tools.py`:

```python
from __future__ import annotations

TOOL_DEFINITIONS = [
    {
        "name": "regenerate_plan",
        "description": "사용자 요청을 반영해 플랜을 다시 생성한다.",
        "parameters": {
            "type": "object",
            "properties": {"instructions": {"type": "string", "description": "수정 방향 자연어 지침"}},
            "required": ["instructions"],
        },
    },
    {
        "name": "confirm",
        "description": "사용자가 현재 플랜을 그대로 확정.",
        "parameters": {"type": "object", "properties": {}},
    },
]
```

- [ ] **Step 2: 테스트 작성**:

```python
from __future__ import annotations

from datetime import date

import pytest

from agents.todo_creation.exceptions import EditAgentError
from agents.todo_creation.multi_turn.nodes.edit_agent import (
    edit_agent_node, route_after_edit_agent,
)
from agents.todo_creation.schemas import AgentDecision, ChatMessage, Day, TaggedPlan, Task


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


def _plan() -> TaggedPlan:
    return TaggedPlan(
        summary_text="요약",
        days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부")])],
    )


@pytest.mark.asyncio
async def test_edit_agent_confirm_tool(base_input, fake_mt_llm):
    fake_mt_llm.agent_decisions = [AgentDecision(tool_name="confirm", tool_args={})]
    state = {
        "input": base_input,
        "history": [ChatMessage(role="user", content=base_input.message)],
        "current_plan": _plan(),
    }
    out = await edit_agent_node(state, _config(fake_mt_llm))
    assert out["confirmed"] is True


@pytest.mark.asyncio
async def test_edit_agent_regenerate_tool(base_input, fake_mt_llm):
    fake_mt_llm.agent_decisions = [AgentDecision(
        tool_name="regenerate_plan", tool_args={"instructions": "마지막 날 가볍게"},
    )]
    state = {"input": base_input, "history": [], "current_plan": _plan()}
    out = await edit_agent_node(state, _config(fake_mt_llm))
    assert out["edit_instructions"] == "마지막 날 가볍게"


@pytest.mark.asyncio
async def test_edit_agent_regenerate_without_instructions_raises(base_input, fake_mt_llm):
    fake_mt_llm.agent_decisions = [AgentDecision(tool_name="regenerate_plan", tool_args={})]
    state = {"input": base_input, "history": [], "current_plan": _plan()}
    with pytest.raises(EditAgentError) as ei:
        await edit_agent_node(state, _config(fake_mt_llm))
    assert ei.value.code == "M9"


def test_route_after_edit_agent_confirm():
    assert route_after_edit_agent({"confirmed": True}) == "commit_invoke"


def test_route_after_edit_agent_regenerate():
    assert route_after_edit_agent({"edit_instructions": "x"}) == "plan_generator"
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_edit_agent.py -v 2>&1 | tail -15
```

Expected: ImportError

- [ ] **Step 4: 구현 작성** — `agents/todo_creation/multi_turn/nodes/edit_agent.py`:

```python
from __future__ import annotations

from typing import Any

from agents.todo_creation.exceptions import EditAgentError
from agents.todo_creation.multi_turn.state import MultiTurnGraphState


async def edit_agent_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    decision = await ports.llm.edit_agent_step(
        history=state["history"], current_plan=state["current_plan"],
    )

    if decision.tool_name == "confirm":
        return {"confirmed": True}

    if decision.tool_name == "regenerate_plan":
        instructions = decision.tool_args.get("instructions")
        if not instructions:
            raise EditAgentError(code="M9", message="regenerate_plan called without instructions")
        return {"edit_instructions": instructions}

    raise EditAgentError(code="M9", message=f"unknown tool: {decision.tool_name}")


def route_after_edit_agent(state: MultiTurnGraphState) -> str:
    if state.get("confirmed"):
        return "commit_invoke"
    if state.get("edit_instructions"):
        return "plan_generator"
    raise EditAgentError(code="M9", message="edit_agent produced no decision")
```

- [ ] **Step 5: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_edit_agent.py -v 2>&1 | tail -10
```

Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add agents/todo_creation/multi_turn/tools.py \
        agents/todo_creation/multi_turn/nodes/edit_agent.py \
        tests/agents/todo_creation/multi_turn/nodes/test_edit_agent.py
git commit -m "feat(todo): edit_agent 노드 (regenerate_plan / confirm 분기)"
```

---

## Phase 11: Commit Invoke

### Task 11.1: commit_invoke_node

**Files:**
- Create: `agents/todo_creation/multi_turn/nodes/commit_invoke.py`
- Create: `tests/agents/todo_creation/multi_turn/nodes/test_commit_invoke.py`

- [ ] **Step 1: 테스트 작성**:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.multi_turn.nodes.commit_invoke import commit_invoke_node
from agents.todo_creation.multi_turn.session_store import InMemorySessionStore
from agents.todo_creation.schemas import Day, SessionState, TaggedPlan, Task


@dataclass
class _Dispatch:
    calls: int = 0
    async def dispatch(self, *, user_id: str) -> None:
        self.calls += 1


@dataclass
class _MtPorts:
    session_store: InMemorySessionStore
    commit_ports: CommitPorts


def _config(mt_ports, now):
    return {"configurable": {"ports": mt_ports, "now": now}}


def _plan(today: date) -> TaggedPlan:
    return TaggedPlan(
        summary_text="요약",
        days=[
            Day(date=today, tasks=[Task(title="오늘 할일", tags=["todo"])]),
            Day(date=date(2026, 5, 27), tasks=[Task(title="내일 일정", tags=["event"])]),
        ],
    )


@pytest.mark.asyncio
async def test_commit_invoke_runs_commit_and_deletes_session(base_input, today, now, session_store):
    await session_store.save(state=SessionState(
        session_id=base_input.session_id, user_id=base_input.user_id, phase="reviewing",
        history=[], parsed_goal=None, current_plan=_plan(today),
        created_at=now, updated_at=now,
    ))
    commit_ports = CommitPorts(
        repository=MemoryTodoRepository(),
        quest_counter=MemoryQuestCounter(),
        quest_dispatch=_Dispatch(),
    )
    mt_ports = _MtPorts(session_store=session_store, commit_ports=commit_ports)

    state = {"input": base_input, "current_plan": _plan(today), "now": now}
    out = await commit_invoke_node(state, _config(mt_ports, now))

    assert out["result"].kind == "committed"
    assert await session_store.load(session_id=base_input.session_id) is None


@pytest.mark.asyncio
async def test_commit_invoke_keeps_session_on_failure(base_input, today, now, session_store):
    await session_store.save(state=SessionState(
        session_id=base_input.session_id, user_id=base_input.user_id, phase="reviewing",
        history=[], parsed_goal=None, current_plan=_plan(today),
        created_at=now, updated_at=now,
    ))
    commit_ports = CommitPorts(
        repository=MemoryTodoRepository(fail_next=True),
        quest_counter=MemoryQuestCounter(),
        quest_dispatch=_Dispatch(),
    )
    mt_ports = _MtPorts(session_store=session_store, commit_ports=commit_ports)

    state = {"input": base_input, "current_plan": _plan(today), "now": now}
    with pytest.raises(Exception):
        await commit_invoke_node(state, _config(mt_ports, now))

    assert await session_store.load(session_id=base_input.session_id) is not None
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_commit_invoke.py -v 2>&1 | tail -15
```

Expected: ImportError

- [ ] **Step 3: 구현 작성** — `agents/todo_creation/multi_turn/nodes/commit_invoke.py`:

```python
from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agents.todo_creation.commit.pipeline import run as commit_run
from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.schemas import CommitInput, TaskCandidate, TurnResult


def _idempotency_key(session_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"multi:{session_id}")


async def commit_invoke_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    now = config["configurable"]["now"]
    input_ = state["input"]
    plan = state["current_plan"]
    today = input_.today

    candidates = [
        TaskCandidate(title=t.title, due_date=d.date, time_hint=t.time_hint, tags=t.tags)
        for d in plan.days for t in d.tasks
    ]
    todos = [c for c in candidates if c.due_date == today]
    events = [c for c in candidates if c.due_date != today]

    commit_input = CommitInput(
        user_id=input_.user_id,
        idempotency_key=_idempotency_key(input_.session_id),
        today=today,
        todos=todos,
        calendar_events=events,
    )
    result = await commit_run(commit_input, ports=ports.commit_ports, now=now)

    await ports.session_store.delete(session_id=input_.session_id)
    return {"result": TurnResult(kind="committed", commit_result=result)}
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_commit_invoke.py -v 2>&1 | tail -10
```

Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/multi_turn/nodes/commit_invoke.py \
        tests/agents/todo_creation/multi_turn/nodes/test_commit_invoke.py
git commit -m "feat(todo): commit_invoke 노드 (commit/pipeline 위임 + session 정리)"
```

---

## Phase 12: Present Node

### Task 12.1: present_node

**Files:**
- Create: `agents/todo_creation/multi_turn/nodes/present.py`
- Create: `tests/agents/todo_creation/multi_turn/nodes/test_present.py`

- [ ] **Step 1: 테스트 작성**:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from agents.todo_creation.multi_turn.nodes.present import present_node
from agents.todo_creation.multi_turn.session_store import InMemorySessionStore
from agents.todo_creation.schemas import (
    ChatMessage, CommitResult, Day, ParsedGoal, TaggedPlan, Task, TurnResult,
)


@dataclass
class _Ports:
    session_store: InMemorySessionStore


def _config(ports, now):
    return {"configurable": {"ports": ports, "now": now}}


@pytest.mark.asyncio
async def test_present_question_saves_session_gathering(base_input, now, session_store):
    state = {
        "input": base_input, "now": now, "phase": "gathering",
        "history": [ChatMessage(role="user", content=base_input.message)],
        "parsed_goal": ParsedGoal(goal_type="정처기"),
        "current_plan": None,
        "follow_up_question": "하루 시간은?",
    }
    out = await present_node(state, _config(_Ports(session_store), now))
    assert out["result"].kind == "question"
    assert out["result"].question == "하루 시간은?"

    saved = await session_store.load(session_id=base_input.session_id)
    assert saved.phase == "gathering"
    assert saved.history[-1].role == "assistant"


@pytest.mark.asyncio
async def test_present_plan_saves_session_reviewing(base_input, now, session_store, today):
    plan = TaggedPlan(
        summary_text="요약",
        days=[Day(date=today, tasks=[Task(title="공부", tags=["학습"])])],
    )
    state = {
        "input": base_input, "now": now, "phase": "gathering",
        "history": [ChatMessage(role="user", content=base_input.message)],
        "parsed_goal": ParsedGoal(),
        "current_plan": plan,
    }
    out = await present_node(state, _config(_Ports(session_store), now))
    assert out["result"].kind == "plan"

    saved = await session_store.load(session_id=base_input.session_id)
    assert saved.phase == "reviewing"
    assert saved.current_plan is not None


@pytest.mark.asyncio
async def test_present_committed_passthrough(base_input, now, session_store):
    committed = TurnResult(
        kind="committed",
        commit_result=CommitResult(todo_ids=[], event_ids=[], quest_distribution_triggered=False),
    )
    state = {"input": base_input, "now": now, "result": committed}
    out = await present_node(state, _config(_Ports(session_store), now))
    assert out["result"].kind == "committed"
    # commit_invoke 가 이미 session 삭제했으므로 present 는 save 하지 않음
    assert await session_store.load(session_id=base_input.session_id) is None
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_present.py -v 2>&1 | tail -15
```

Expected: ImportError

- [ ] **Step 3: 구현 작성** — `agents/todo_creation/multi_turn/nodes/present.py`:

```python
from __future__ import annotations

from typing import Any

from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.schemas import ChatMessage, SessionState, TurnResult


async def present_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    now = config["configurable"]["now"]
    input_ = state["input"]

    # commit_invoke 가 이미 result + session.delete 완료한 분기
    if state.get("result") and state["result"].kind == "committed":
        return {"result": state["result"]}

    follow_up = state.get("follow_up_question")
    current_plan = state.get("current_plan")
    history = list(state.get("history") or [])

    if follow_up is not None:
        history.append(ChatMessage(role="assistant", content=follow_up))
        result = TurnResult(kind="question", question=follow_up)
        new_phase = "gathering"
    else:
        assert current_plan is not None
        history.append(ChatMessage(role="assistant", content=current_plan.summary_text))
        result = TurnResult(kind="plan", plan=current_plan)
        new_phase = "reviewing"

    session_state = SessionState(
        session_id=input_.session_id, user_id=input_.user_id, phase=new_phase,
        history=history[-20:],
        parsed_goal=state.get("parsed_goal"),
        current_plan=current_plan,
        created_at=now, updated_at=now,
    )
    await ports.session_store.save(state=session_state)
    return {"result": result}
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/nodes/test_present.py -v 2>&1 | tail -10
```

Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/multi_turn/nodes/present.py \
        tests/agents/todo_creation/multi_turn/nodes/test_present.py
git commit -m "feat(todo): present 노드 (TurnResult 패키징 + session 저장)"
```

---

## Phase 13: Graph Builder

### Task 13.1: build_multi_turn_graph

**Files:**
- Create: `agents/todo_creation/multi_turn/graph.py`
- Create: `tests/agents/todo_creation/multi_turn/test_graph.py`

- [ ] **Step 1: 테스트 작성**:

```python
from __future__ import annotations

from agents.todo_creation.multi_turn.graph import build_multi_turn_graph


def test_graph_compiles_with_expected_nodes():
    graph = build_multi_turn_graph()
    node_ids = set(graph.get_graph().nodes.keys())
    expected = {
        "validate", "phase_router", "planner_judge", "follow_up",
        "plan_generator", "tagger", "edit_agent", "commit_invoke", "present",
    }
    assert expected.issubset(node_ids)


def test_graph_mermaid_includes_phase_router_and_edit_agent():
    graph = build_multi_turn_graph()
    mmd = graph.get_graph().draw_mermaid()
    assert "phase_router" in mmd
    assert "edit_agent" in mmd
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/test_graph.py -v 2>&1 | tail -10
```

Expected: ImportError

- [ ] **Step 3: 구현 작성** — `agents/todo_creation/multi_turn/graph.py`:

```python
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.multi_turn.nodes.commit_invoke import commit_invoke_node
from agents.todo_creation.multi_turn.nodes.edit_agent import (
    edit_agent_node, route_after_edit_agent,
)
from agents.todo_creation.multi_turn.nodes.follow_up import follow_up_node
from agents.todo_creation.multi_turn.nodes.phase_router import (
    phase_router_node, route_after_phase_router,
)
from agents.todo_creation.multi_turn.nodes.plan_generator import plan_generator_node
from agents.todo_creation.multi_turn.nodes.planner_judge import (
    planner_judge_node, route_after_judge,
)
from agents.todo_creation.multi_turn.nodes.present import present_node
from agents.todo_creation.multi_turn.nodes.tagger import tagger_node
from agents.todo_creation.multi_turn.nodes.validate import validate_node
from agents.todo_creation.multi_turn.state import MultiTurnGraphState


def build_multi_turn_graph():
    g = StateGraph(MultiTurnGraphState)

    g.add_node("validate", validate_node)
    g.add_node("phase_router", phase_router_node)
    g.add_node("planner_judge", planner_judge_node, retry=RetryPolicy(max_attempts=2, retry_on=(LLMFailedError,)))
    g.add_node("follow_up", follow_up_node, retry=RetryPolicy(max_attempts=2, retry_on=(LLMFailedError,)))
    g.add_node("plan_generator", plan_generator_node, retry=RetryPolicy(max_attempts=2, retry_on=(LLMFailedError,)))
    g.add_node("tagger", tagger_node, retry=RetryPolicy(max_attempts=2, retry_on=(LLMFailedError,)))
    g.add_node("edit_agent", edit_agent_node, retry=RetryPolicy(max_attempts=1, retry_on=(LLMFailedError,)))
    g.add_node("commit_invoke", commit_invoke_node)
    g.add_node("present", present_node)

    g.add_edge(START, "validate")
    g.add_edge("validate", "phase_router")
    g.add_conditional_edges(
        "phase_router", route_after_phase_router,
        {"planner_judge": "planner_judge", "edit_agent": "edit_agent"},
    )
    g.add_conditional_edges(
        "planner_judge", route_after_judge,
        {"plan_generator": "plan_generator", "follow_up": "follow_up"},
    )
    g.add_edge("follow_up", "present")
    g.add_edge("plan_generator", "tagger")
    g.add_edge("tagger", "present")
    g.add_conditional_edges(
        "edit_agent", route_after_edit_agent,
        {"plan_generator": "plan_generator", "commit_invoke": "commit_invoke"},
    )
    g.add_edge("commit_invoke", "present")
    g.add_edge("present", END)

    return g.compile()
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/test_graph.py -v 2>&1 | tail -10
```

Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/multi_turn/graph.py \
        tests/agents/todo_creation/multi_turn/test_graph.py
git commit -m "feat(todo): multi_turn LangGraph 빌더 (conditional edges + RetryPolicy)"
```

---

## Phase 14: Pipeline & Debug 확장

### Task 14.1: debug.py 확장

**Files:**
- Modify: `agents/todo_creation/debug.py`

- [ ] **Step 1: Kind 확장** — `agents/todo_creation/debug.py` 의 `Kind` 라인 변경:

```python
Kind = Literal["generate", "commit", "multi_turn"]
```

- [ ] **Step 2: summary 라인 변경** — `log_start` 안의 `summary = ...` 블록 교체:

```python
    summary = (
        getattr(input, "prompt", None)
        or getattr(input, "message", None)
        or (
            f"todos={len(getattr(input, 'todos', []))} "
            f"events={len(getattr(input, 'calendar_events', []))}"
        )
    )
```

- [ ] **Step 3: log_step key 추가** — `log_step` 의 key 튜플에 다음 추가:

```python
        "phase",
        "judgment",
        "follow_up_question",
        "plan_draft",
        "current_plan",
        "edit_instructions",
        "confirmed",
```

- [ ] **Step 4: import 검증**

```bash
uv run python -c "from agents.todo_creation.debug import log_start, log_step, log_end; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: 커밋**

```bash
git add agents/todo_creation/debug.py
git commit -m "feat(todo): debug 로거 multi_turn kind + 신규 state 키 지원"
```

### Task 14.2: pipeline.py — run_turn

**Files:**
- Create: `agents/todo_creation/multi_turn/pipeline.py`
- Create: `tests/agents/todo_creation/multi_turn/test_pipeline.py`

- [ ] **Step 1: 통합 테스트 작성**:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.multi_turn.pipeline import MultiTurnPorts, run_turn
from agents.todo_creation.schemas import (
    AgentDecision, ChatMessage, Day, ParsedGoal, PlanDraft, PlannerJudgment,
    SessionState, TaggedPlan, Task,
)


@dataclass
class _Dispatch:
    calls: int = 0
    async def dispatch(self, *, user_id: str) -> None:
        self.calls += 1


def _make_ports(fake_mt_llm, session_store, *, fail_repo=False) -> MultiTurnPorts:
    return MultiTurnPorts(
        llm=fake_mt_llm,
        session_store=session_store,
        commit_ports=CommitPorts(
            repository=MemoryTodoRepository(fail_next=fail_repo),
            quest_counter=MemoryQuestCounter(),
            quest_dispatch=_Dispatch(),
        ),
    )


def _plan_draft(today: date) -> PlanDraft:
    return PlanDraft(summary_text="요약", days=[Day(date=today, tasks=[Task(title="공부")])])


def _tagged_plan(today: date) -> TaggedPlan:
    return TaggedPlan(summary_text="요약", days=[Day(date=today, tasks=[Task(title="공부", tags=["학습"])])])


def _reviewing_state(input_, today, now):
    return SessionState(
        session_id=input_.session_id, user_id=input_.user_id, phase="reviewing",
        history=[ChatMessage(role="user", content="이전")],
        parsed_goal=ParsedGoal(goal_type="정처기"),
        current_plan=_tagged_plan(today),
        created_at=now, updated_at=now,
    )


@pytest.mark.asyncio
async def test_turn1_insufficient_returns_question(base_input, now, today, fake_mt_llm, session_store):
    fake_mt_llm.judge_responses = [PlannerJudgment(
        is_sufficient=False, missing_aspects=["하루 시간"], parsed_goal=ParsedGoal(goal_type="정처기"),
    )]
    fake_mt_llm.follow_up_responses = ["하루 학습 시간은?"]

    result = await run_turn(base_input, ports=_make_ports(fake_mt_llm, session_store), now=now)
    assert result.kind == "question"
    assert result.question == "하루 학습 시간은?"
    saved = await session_store.load(session_id=base_input.session_id)
    assert saved.phase == "gathering"


@pytest.mark.asyncio
async def test_turn1_sufficient_returns_plan(base_input, now, today, fake_mt_llm, session_store):
    fake_mt_llm.judge_responses = [PlannerJudgment(
        is_sufficient=True, missing_aspects=[],
        parsed_goal=ParsedGoal(goal_type="정처기", daily_capacity="3h"),
    )]
    fake_mt_llm.plan_responses = [_plan_draft(today)]
    fake_mt_llm.tag_responses = [_tagged_plan(today)]

    result = await run_turn(base_input, ports=_make_ports(fake_mt_llm, session_store), now=now)
    assert result.kind == "plan"
    saved = await session_store.load(session_id=base_input.session_id)
    assert saved.phase == "reviewing"


@pytest.mark.asyncio
async def test_turn3a_confirm_commits_and_clears_session(base_input, now, today, fake_mt_llm, session_store):
    await session_store.save(state=_reviewing_state(base_input, today, now))
    fake_mt_llm.agent_decisions = [AgentDecision(tool_name="confirm", tool_args={})]

    result = await run_turn(
        base_input.model_copy(update={"message": "확정해줘"}),
        ports=_make_ports(fake_mt_llm, session_store),
        now=now,
    )
    assert result.kind == "committed"
    assert await session_store.load(session_id=base_input.session_id) is None


@pytest.mark.asyncio
async def test_turn3b_regenerate_returns_new_plan(base_input, now, today, fake_mt_llm, session_store):
    await session_store.save(state=_reviewing_state(base_input, today, now))
    fake_mt_llm.agent_decisions = [AgentDecision(
        tool_name="regenerate_plan", tool_args={"instructions": "더 가볍게"},
    )]
    fake_mt_llm.plan_responses = [_plan_draft(today)]
    fake_mt_llm.tag_responses = [_tagged_plan(today)]

    result = await run_turn(
        base_input.model_copy(update={"message": "더 가볍게 해줘"}),
        ports=_make_ports(fake_mt_llm, session_store),
        now=now,
    )
    assert result.kind == "plan"
    assert fake_mt_llm.last_plan_edit_instructions == ["더 가볍게"]


@pytest.mark.asyncio
async def test_commit_failure_preserves_session(base_input, now, today, fake_mt_llm, session_store):
    await session_store.save(state=_reviewing_state(base_input, today, now))
    fake_mt_llm.agent_decisions = [AgentDecision(tool_name="confirm", tool_args={})]

    with pytest.raises(Exception):
        await run_turn(
            base_input.model_copy(update={"message": "확정"}),
            ports=_make_ports(fake_mt_llm, session_store, fail_repo=True),
            now=now,
        )
    assert await session_store.load(session_id=base_input.session_id) is not None
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/test_pipeline.py -v 2>&1 | tail -15
```

Expected: ImportError

- [ ] **Step 3: pipeline 구현** — `agents/todo_creation/multi_turn/pipeline.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.debug import log_end, log_start, log_step
from agents.todo_creation.multi_turn.graph import build_multi_turn_graph
from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.protocols import MultiTurnLLMPort, SessionStorePort
from agents.todo_creation.schemas import MultiTurnInput, TurnResult


@dataclass
class MultiTurnPorts:
    llm: MultiTurnLLMPort
    session_store: SessionStorePort
    commit_ports: CommitPorts


_GRAPH = build_multi_turn_graph()


async def run_turn(
    input: MultiTurnInput,
    *,
    ports: MultiTurnPorts,
    now: datetime,
) -> TurnResult:
    initial: MultiTurnGraphState = {"input": input, "now": now}
    config = {"configurable": {"ports": ports, "now": now}}

    log_start(input, "multi_turn")

    final: Any = None
    step = 0
    async for mode, chunk in _GRAPH.astream(
        initial, config=config, stream_mode=["updates", "values"]
    ):
        if mode == "updates":
            for node_name, update in chunk.items():
                step += 1
                log_step(step, node_name, update)
        elif mode == "values":
            final = chunk

    log_end(final)

    assert final is not None
    result = final.get("result")
    assert result is not None
    return result
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/agents/todo_creation/multi_turn/ -v 2>&1 | tail -30
```

Expected: 모든 multi_turn 테스트 PASS

- [ ] **Step 5: 회귀 확인**

```bash
uv run pytest 2>&1 | tail -10
```

Expected: 기존 테스트 영향 없음

- [ ] **Step 6: 커밋**

```bash
git add agents/todo_creation/multi_turn/pipeline.py \
        tests/agents/todo_creation/multi_turn/test_pipeline.py
git commit -m "feat(todo): multi_turn run_turn entry + 통합 시나리오 5개"
```

---

## Phase 15: OpenAI Adapter

### Task 15.1: OpenAIMultiTurnLLM

**Files:**
- Create: `adapters/todo_creation/openai_multi_turn.py`
- Create: `tests/adapters/todo_creation/test_openai_multi_turn.py`

- [ ] **Step 1: 기존 openai_llm.py 패턴 확인**

```bash
cd /Users/jpaper/Documents/projects/mongle-village-todo
cat adapters/todo_creation/openai_llm.py | head -60
```

Expected: 기존 single_turn 용 OpenAI 어댑터 코드. 동일 패턴 차용.

- [ ] **Step 2: 어댑터 구현** — `adapters/todo_creation/openai_multi_turn.py`:

```python
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date

from openai import AsyncOpenAI

from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.multi_turn.tools import TOOL_DEFINITIONS
from agents.todo_creation.schemas import (
    AgentDecision, ChatMessage, ParsedGoal, PlanDraft, PlannerJudgment, TaggedPlan,
)


@dataclass
class OpenAIMultiTurnLLM:
    model: str = "gpt-4o-mini"
    client: AsyncOpenAI | None = None

    def _client(self) -> AsyncOpenAI:
        if self.client is None:
            self.client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        return self.client

    async def judge_planner(self, *, history, previous_goal, today) -> PlannerJudgment:
        try:
            resp = await self._client().beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"오늘은 {today.isoformat()}. "
                            "사용자 메시지와 이전 goal 로부터 정보 충분성 판단. "
                            "이전 parsed_goal 을 보존하며 새 정보로 갱신. "
                            f"이전 parsed_goal: {previous_goal.model_dump_json() if previous_goal else 'null'}"
                        ),
                    },
                    *[{"role": m.role, "content": m.content} for m in history],
                ],
                response_format=PlannerJudgment,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is None:
                raise LLMOutputError("parse returned None")
            return parsed
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e

    async def generate_follow_up(self, *, missing_aspects, history) -> str:
        try:
            resp = await self._client().chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"한국어 1~2문장의 짧은 꼬리 질문 생성. 부족 정보: {', '.join(missing_aspects)}",
                    },
                    *[{"role": m.role, "content": m.content} for m in history],
                ],
            )
            content = resp.choices[0].message.content
            if not content:
                raise LLMOutputError("empty follow_up")
            return content.strip()
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e

    async def generate_plan(self, *, parsed_goal, today, edit_instructions) -> PlanDraft:
        try:
            sys_prompt = (
                f"오늘은 {today.isoformat()}. "
                "주어진 parsed_goal 에 맞춰 일자별 플랜 JSON 생성. "
                "summary_text 는 ≤1500자 한국어."
            )
            if edit_instructions:
                sys_prompt += f"\n[수정 지침] {edit_instructions}"
            resp = await self._client().beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": parsed_goal.model_dump_json()},
                ],
                response_format=PlanDraft,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is None:
                raise LLMOutputError("parse returned None")
            return parsed
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e

    async def tag_plan(self, *, plan_draft, parsed_goal) -> TaggedPlan:
        try:
            resp = await self._client().beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "plan_draft 의 각 task 에 자유 형식 한국어 태그 부여. "
                            f"목표 컨텍스트: {parsed_goal.model_dump_json()}"
                        ),
                    },
                    {"role": "user", "content": plan_draft.model_dump_json()},
                ],
                response_format=TaggedPlan,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is None:
                raise LLMOutputError("parse returned None")
            return parsed
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e

    async def edit_agent_step(self, *, history, current_plan) -> AgentDecision:
        try:
            resp = await self._client().chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "현재 플랜과 사용자 메시지를 보고 적절한 도구 호출. "
                            "사용자 수정 요청 → regenerate_plan(instructions), 확정 의도 → confirm(). "
                            f"\n현재 플랜: {current_plan.model_dump_json()}"
                        ),
                    },
                    *[{"role": m.role, "content": m.content} for m in history],
                ],
                tools=[{"type": "function", "function": t} for t in TOOL_DEFINITIONS],
                tool_choice="required",
            )
            tool_calls = resp.choices[0].message.tool_calls or []
            if not tool_calls:
                raise LLMOutputError("no tool_call returned")
            call = tool_calls[0]
            args = json.loads(call.function.arguments or "{}")
            return AgentDecision(tool_name=call.function.name, tool_args=args)
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e
```

- [ ] **Step 3: Contract 테스트 작성**:

```python
from __future__ import annotations

import os
from datetime import date

import pytest

from adapters.todo_creation.openai_multi_turn import OpenAIMultiTurnLLM
from agents.todo_creation.schemas import (
    ChatMessage, Day, ParsedGoal, TaggedPlan, Task,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_OPENAI") != "1",
    reason="RUN_REAL_OPENAI=1 required",
)


@pytest.mark.asyncio
async def test_judge_planner_real_call():
    llm = OpenAIMultiTurnLLM()
    j = await llm.judge_planner(
        history=[ChatMessage(role="user", content="3일 후 정보처리기사 시험")],
        previous_goal=None,
        today=date(2026, 5, 25),
    )
    assert j.parsed_goal.goal_type is not None or j.missing_aspects


@pytest.mark.asyncio
async def test_edit_agent_step_real_call():
    llm = OpenAIMultiTurnLLM()
    plan = TaggedPlan(
        summary_text="3일 학습 플랜",
        days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부", tags=["학습"])])],
    )
    d = await llm.edit_agent_step(
        history=[ChatMessage(role="user", content="이대로 확정")],
        current_plan=plan,
    )
    assert d.tool_name in {"confirm", "regenerate_plan"}
```

- [ ] **Step 4: skipif 검증**

```bash
uv run pytest tests/adapters/todo_creation/test_openai_multi_turn.py -v 2>&1 | tail -10
```

Expected: 2 skipped

- [ ] **Step 5: 커밋**

```bash
git add adapters/todo_creation/openai_multi_turn.py \
        tests/adapters/todo_creation/test_openai_multi_turn.py
git commit -m "feat(todo): OpenAIMultiTurnLLM 어댑터 + contract test (gated)"
```

---

## Phase 16: 문서 갱신

### Task 16.1: architecture.mmd MULTI 서브그래프 갱신

**Files:**
- Modify: `docs/features/todo/architecture.mmd`

- [ ] **Step 1: 현재 다이어그램 확인**

```bash
cd /Users/jpaper/Documents/projects/mongle-village-todo
grep -n "MULTI" docs/features/todo/architecture.mmd
```

- [ ] **Step 2: MULTI 서브그래프 블록 교체** — `docs/features/todo/architecture.mmd` 의 `subgraph MULTI["멀티턴 TODO/플랜 생성"]` 부터 그 `end` 까지 다음으로 교체:

```mermaid
 subgraph MULTI["멀티턴 TODO/플랜 생성"]
    direction TB
        MA@{ label: "User Input
        자연어 메시지 (≤600자, 한국어 위주)" }
        MV{"Validation
        • 길이 ≤600자 (M1)
        • 빈 입력 (M2)
        • 한글 비율 ≥0.3 (M3)"}
        MVE[/"에러 응답"/]
        MPR{"phase_router
        SessionStore 조회"}
        MPS["LLM Planner judge
        is_sufficient + parsed_goal 갱신"]
        MQ{"is_sufficient?"}
        MFU["LLM Follow-up
        꼬리 질문 생성"]
        MPG["LLM Plan Generator
        일자별 플랜 (≤1500자 + truncate fallback)"]
        MTG["LLM Tagger
        자유 형식 태그"]
        EA["LLM Edit Agent
        tools: regenerate_plan / confirm"]
        ME["present
        TurnResult + SessionStore.save"]
        MC["commit_invoke
        commit/pipeline.run() 위임"]
  end
```

그리고 그 아래 MULTI 의 엣지 정의 블록 (`MA --> MV` 부터 `ME -- 확정 --> MC` 까지) 을 다음으로 교체:

```
    MA --> MV
    MV -- 실패 --> MVE
    MV -- 통과 --> MPR
    MPR -- gathering --> MPS
    MPR -- reviewing --> EA
    MPS --> MQ
    MQ -- 부족 --> MFU --> ME
    MQ -- 충분 --> MPG --> MTG --> ME
    EA -- regenerate_plan --> MPG
    EA -- confirm --> MC --> ME
    ME --> COMMIT
```

마지막으로 classDef 매핑 부분에서:
- `MAU:::input` 제거 (사용자 답변 노드는 다음 turn 진입으로 대체됨)
- `EA:::ai` 추가
- `MPR:::process` 추가

- [ ] **Step 3: mermaid 노드 정합성 검증**

```bash
uv run python -c "
from agents.todo_creation.multi_turn.graph import build_multi_turn_graph
g = build_multi_turn_graph()
print(g.get_graph().draw_mermaid())
" 2>&1 | head -30
```

Expected: 생성된 mermaid 의 노드 이름이 다이어그램의 노드와 일치.

- [ ] **Step 4: 커밋**

```bash
git add docs/features/todo/architecture.mmd
git commit -m "docs(todo): architecture.mmd MULTI 서브그래프 as-built 갱신"
```

### Task 16.2: docs/features/todo/CLAUDE.md §7 갱신

**Files:**
- Modify: `docs/features/todo/CLAUDE.md`

- [ ] **Step 1: §7 절을 결정 사항 표로 교체**

`docs/features/todo/CLAUDE.md` 의 `## 7. 미결 사항 (Open Questions)` 절 전체를 다음으로 교체:

```markdown
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
```

- [ ] **Step 2: 커밋**

```bash
git add docs/features/todo/CLAUDE.md
git commit -m "docs(todo): §7 미결사항 → 결정 사항 표로 갱신"
```

### Task 16.3: CHANGELOG 갱신

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Unreleased/Added 항목 추가**

`CHANGELOG.md` 의 `## [Unreleased]` 아래 `### Added` 섹션에 다음 추가:

```markdown
- **multi_turn TODO/플랜 챗봇** (`agents/todo_creation/multi_turn/`):
  - Hybrid LangGraph (정보수집=결정론, 수정루프=tool-calling)
  - SessionStorePort + InMemorySessionStore (Port 확정, MySQL 어댑터는 후속)
  - 9 노드 + RetryPolicy + C3 재생성+truncate fallback
  - FakeMultiTurnLLM (큐 기반) + 통합 시나리오 5개
  - OpenAIMultiTurnLLM 어댑터 + gated contract test
  - 설계서: `docs/superpowers/specs/2026-05-25-todo-multiturn-design.md`
```

- [ ] **Step 2: 커밋**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG multi_turn 챗봇 추가 항목"
```

---

## Phase 17: 최종 검증

### Task 17.1: 전체 테스트 + 커버리지 + PR

- [ ] **Step 1: 전체 테스트 + 커버리지**

```bash
cd /Users/jpaper/Documents/projects/mongle-village-todo
uv run pytest --cov=agents/todo_creation/multi_turn --cov-report=term-missing 2>&1 | tail -40
```

Expected:
- 모든 테스트 PASS
- multi_turn 커버리지 ≥ 80%

- [ ] **Step 2: 회귀 확인**

```bash
uv run pytest tests/agents/todo_creation/single_turn tests/agents/todo_creation/commit -v 2>&1 | tail -15
```

Expected: 기존 single_turn / commit 테스트 모두 PASS

- [ ] **Step 3: PR 푸시 (사용자 확정 시)**

```bash
git push -u origin feat/todo-multiturn
gh pr create --base main --head feat/todo-multiturn \
  --title "feat(todo): multi_turn 챗봇 (Hybrid 그래프 + tool-calling)" \
  --body "$(cat <<'EOF'
## Summary

- Hybrid LangGraph 멀티턴 TODO/플랜 챗봇 구현
- 정보수집(planner_judge → follow_up | plan_generator → tagger) 결정론적, 수정 루프(edit_agent) tool-calling
- SessionStorePort + InMemorySessionStore (MySQL 어댑터는 후속 PR)
- commit/pipeline.run() 위임 (자체 commit 노드 없음)
- 설계서: docs/superpowers/specs/2026-05-25-todo-multiturn-design.md

## Test plan

- [x] 단위 테스트 (9 노드 + session_store)
- [x] 통합 시나리오 (Turn1 부족/충분, Turn3a 확정, Turn3b 수정, commit 실패 보존)
- [x] OpenAI contract test (RUN_REAL_OPENAI=1 시 통과)
- [x] 회귀: single_turn / commit 영향 없음
- [x] multi_turn 커버리지 ≥ 80%
EOF
)"
```

Expected: PR URL 출력

---

## Self-Review Checklist (작성자 자체 검증 완료)

**Spec coverage:**
- §1 핵심 결정 — Task 5.1 (한글 휴리스틱), Task 8.1 (C3), Task 10.1 (tool 집합) — ✅
- §2 그래프 — Task 13.1 — ✅
- §3 디렉토리 — File Structure 섹션 — ✅
- §4 핵심 타입 — Task 1.1 — ✅
- §5 포트 — Task 2.1, Task 14.2 — ✅
- §6 시나리오 — Task 14.2 통합 테스트 — ✅
- §7 에러 & 재시도 — Task 13.1 (RetryPolicy) + Task 8.1 (C3) + Task 10.1 (M9) — ✅
- §8 테스트 — 모든 Task 의 Step 1 (테스트 우선) — ✅
- §9 영향받는 기존 파일 — Task 14.1, Task 16.* — ✅
- §10 범위 밖 — 플랜에서 의도적 deferred (MySQL, Streamlit, TTL)

**Placeholder scan:** "TBD" / "TODO" / "Similar to Task N" 없음. 모든 step 에 실제 코드/명령.

**Type consistency:**
- `ChatMessage`, `ParsedGoal`, `PlannerJudgment`, `PlanDraft`, `TaggedPlan` 명명 일관
- `route_after_phase_router` / `route_after_judge` / `route_after_edit_agent` 일관
- 테스트 헬퍼 `_Ports` / `_config()` 패턴 일관
- `MultiTurnLLMPort` 메서드 시그니처 (keyword-only) 일관

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-25-todo-multiturn.md`. Two execution options:

**1. Subagent-Driven (recommended)** — 각 Task 마다 fresh subagent 디스패치. Task 간 리뷰. Fast iteration + isolated context. Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — 현재 세션에서 batch 로 실행, 수동 체크포인트. Use `superpowers:executing-plans`.

**Which approach?**
