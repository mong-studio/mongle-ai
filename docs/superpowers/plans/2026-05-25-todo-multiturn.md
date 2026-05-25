# TODO Multi-turn Unified Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `agents/todo_creation/` 의 single 모드와 multi 모드를 단일 `generate_graph` 로 통합. multi 모드는 `checkpointer + interrupt(follow_up)` 패턴. 이전 multi-only 부산물 어댑터(`openai_multi_turn.py`, `fake_multi_turn_llm.py`)는 단일 `LLMPort` 로 흡수 후 폐기. `commit_graph` 는 분리 유지.

**Architecture:** 단일 컴파일 그래프(`checkpointer=MemorySaver`) 가 mode 필드를 보고 `single_validate` 또는 `multi_validate` 로 `Command(goto=...)` 분기. multi 경로는 `planner` → (`follow_up + interrupt` | `plan_generator` → `tagger`) 루프. 양 경로는 `date_router` 로 fan-in 한 뒤 END. plan 검토·확정은 클라가 별도 `commit_graph` 호출.

**Tech Stack:** Python 3.12, LangGraph 0.2+ (StateGraph, Command, interrupt, MemorySaver, RetryPolicy), Pydantic v2 (discriminated union), pytest + pytest-asyncio, character_creation 의 RetryPolicy·debug·ports 패턴.

**Working directory:** `/Users/jpaper/Documents/projects/mongle-village` (current main worktree). 이전 plan 의 `mongle-village-todo` 경로 명시는 무효.
**Branch:** plan 실행 sub-skill 이 결정. 본 plan 은 spec commit `640c876` 머지된 `main` 기준.
**Spec:** [`docs/superpowers/specs/2026-05-25-todo-multiturn-design.md`](../specs/2026-05-25-todo-multiturn-design.md)
**Replaces:** 본 파일은 spec 폐기와 일관되게 이전 multi-only plan(SessionStorePort + edit_agent + phase_router + commit_invoke)을 폐기·대체.

---

## File Structure

### Create
- `agents/todo_creation/pipeline.py`
- `agents/todo_creation/graph.py`
- `agents/todo_creation/state.py`
- `agents/todo_creation/nodes/__init__.py`
- `agents/todo_creation/nodes/entry.py`
- `agents/todo_creation/multi_turn/__init__.py`
- `agents/todo_creation/multi_turn/nodes/__init__.py`
- `agents/todo_creation/multi_turn/nodes/validate.py`
- `agents/todo_creation/multi_turn/nodes/planner.py`
- `agents/todo_creation/multi_turn/nodes/follow_up.py`
- `agents/todo_creation/multi_turn/nodes/plan_generator.py`
- `agents/todo_creation/multi_turn/nodes/tagger.py`
- `tests/agents/todo_creation/nodes/__init__.py`
- `tests/agents/todo_creation/nodes/test_entry.py`
- `tests/agents/todo_creation/multi_turn/__init__.py`
- `tests/agents/todo_creation/multi_turn/nodes/__init__.py`
- `tests/agents/todo_creation/multi_turn/nodes/test_validate.py`
- `tests/agents/todo_creation/multi_turn/nodes/test_planner.py`
- `tests/agents/todo_creation/multi_turn/nodes/test_follow_up.py`
- `tests/agents/todo_creation/multi_turn/nodes/test_plan_generator.py`
- `tests/agents/todo_creation/multi_turn/nodes/test_tagger.py`
- `tests/agents/todo_creation/test_graph.py`
- `tests/agents/todo_creation/test_pipeline.py`

### Modify
- `agents/todo_creation/schemas.py` — `SingleGenerateInput`/`MultiGenerateInput`/`GenerateInput` Union, `GenerateResult`/`FollowUpResult`/`TurnResult` Union 추가
- `agents/todo_creation/protocols.py` — `LLMPort` 에 4 메서드 추가
- `agents/todo_creation/exceptions.py` — `ThreadNotFoundError` 추가
- `adapters/todo_creation/openai_llm.py` — 4 메서드 흡수
- `adapters/todo_creation/fake_llm.py` — 4 메서드 흡수 (`fail_times`/`responses` 큐 패턴 유지)
- `tests/adapters/todo_creation/test_openai_llm.py` — 4 메서드 모킹 케이스 흡수
- `streamlit_app/app.py` — 통합 그래프 사용
- `CHANGELOG.md`
- `docs/features/todo/architecture.mmd`
- `docs/features/todo/CLAUDE.md` — §4 갱신

### Delete
- `agents/todo_creation/single_turn/pipeline.py`
- `agents/todo_creation/single_turn/graph.py`
- `agents/todo_creation/single_turn/state.py`
- `tests/agents/todo_creation/single_turn/test_pipeline.py`
- `adapters/todo_creation/openai_multi_turn.py`
- `adapters/todo_creation/fake_multi_turn_llm.py`
- `tests/adapters/todo_creation/test_openai_multi_turn.py`

---

## Phase A — Foundation

### Task A1: schemas Union 입력 + TurnResult Union

**Files:** Modify `agents/todo_creation/schemas.py`; Test `tests/agents/todo_creation/test_schemas.py`.

- [ ] **Step 1: 실패 테스트**

```python
from datetime import date
import pytest
from pydantic import TypeAdapter, ValidationError as PydanticValidationError
from agents.todo_creation.schemas import (
    SingleGenerateInput, MultiGenerateInput, GenerateInput,
    GenerateResult, FollowUpResult, TurnResult,
)

def test_single_input_max_200():
    assert SingleGenerateInput(user_id="u1", prompt="a"*200, today=date(2026,5,25)).mode == "single"

def test_single_input_over_200_rejected():
    with pytest.raises(PydanticValidationError):
        SingleGenerateInput(user_id="u1", prompt="a"*201, today=date(2026,5,25))

def test_multi_input_max_600():
    inp = MultiGenerateInput(user_id="u1", message="가"*600, today=date(2026,5,25))
    assert inp.mode == "multi"
    assert inp.thread_id is None

def test_multi_input_over_600_rejected():
    with pytest.raises(PydanticValidationError):
        MultiGenerateInput(user_id="u1", message="가"*601, today=date(2026,5,25))

def test_generate_input_discriminator_single():
    parsed = TypeAdapter(GenerateInput).validate_python(
        {"mode":"single","user_id":"u1","prompt":"x","today":"2026-05-25"})
    assert isinstance(parsed, SingleGenerateInput)

def test_generate_input_discriminator_multi():
    parsed = TypeAdapter(GenerateInput).validate_python(
        {"mode":"multi","user_id":"u1","message":"안녕","today":"2026-05-25"})
    assert isinstance(parsed, MultiGenerateInput)

def test_turn_result_discriminator():
    a = TypeAdapter(TurnResult)
    c = a.validate_python({"kind":"candidates","thread_id":"t1","todos":[],"calendar_events":[]})
    f = a.validate_python({"kind":"follow_up","thread_id":"t1","question":"?","missing_aspects":[]})
    assert isinstance(c, GenerateResult)
    assert isinstance(f, FollowUpResult)
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/agents/todo_creation/test_schemas.py -v`. Expected: ImportError.
- [ ] **Step 3: 구현** — `agents/todo_creation/schemas.py` 끝에 spec §3.1 의 6 모델 + 두 Union 추가 (`Annotated[A|B, Field(discriminator="mode"|"kind")]`). 기존 `TaskCandidate` 변경 없음.
- [ ] **Step 4: 통과 확인** — Expected: 7 passed.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/schemas.py tests/agents/todo_creation/test_schemas.py
git commit -m "feat(todo): add unified generate Input/TurnResult discriminated unions"
```

---

### Task A2: exceptions — ThreadNotFoundError

**Files:** Modify `agents/todo_creation/exceptions.py`; Test `tests/agents/todo_creation/test_exceptions.py`.

- [ ] **Step 1: 실패 테스트**

```python
def test_thread_not_found_inherits():
    from agents.todo_creation.exceptions import ThreadNotFoundError, TodoCreationError
    assert isinstance(ThreadNotFoundError("missing"), TodoCreationError)
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현** — `exceptions.py` 에 `class ThreadNotFoundError(TodoCreationError): """4xx — invalid or expired LangGraph thread_id."""`.
- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/exceptions.py tests/agents/todo_creation/test_exceptions.py
git commit -m "feat(todo): add ThreadNotFoundError"
```

---

### Task A3: state.py 신규 (GenerateState)

**Files:** Create `agents/todo_creation/state.py`. (TypedDict 만 — 별도 단위 테스트 없음.)

- [ ] **Step 1: state.py 작성** — spec §3.2 의사코드 그대로

```python
from datetime import date, datetime
from typing import Literal, TypedDict
from agents.todo_creation.schemas import TaskCandidate

class Turn(TypedDict):
    role: Literal["user", "assistant"]
    content: str

class ParsedGoal(TypedDict, total=False):
    goal_text: str
    deadline: date | None
    daily_capacity_minutes: int | None

class PlanDay(TypedDict):
    date: date
    tasks: list[TaskCandidate]

class GenerateState(TypedDict, total=False):
    mode: Literal["single", "multi"]
    user_id: str
    today: date
    now: datetime
    prompt: str
    split_tasks: list[TaskCandidate]
    message: str
    history: list[Turn]
    parsed_goal: ParsedGoal | None
    sufficiency: bool | None
    missing_aspects: list[str]
    follow_up_question: str | None
    plan: list[PlanDay] | None
    summary_text: str | None
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]
    error: Exception | None
```

- [ ] **Step 2: import smoke**

```bash
uv run python -c "from agents.todo_creation.state import GenerateState, Turn, ParsedGoal, PlanDay; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: commit**

```bash
git add agents/todo_creation/state.py
git commit -m "feat(todo): add unified GenerateState TypedDict"
```

---

### Task A4: protocols — LLMPort 4 신규 메서드

**Files:** Modify `agents/todo_creation/protocols.py`; Test `tests/agents/todo_creation/test_protocols.py`.

- [ ] **Step 1: 실패 테스트**

```python
import inspect
from agents.todo_creation.protocols import LLMPort
def test_llm_port_has_five_methods():
    names = {n for n,_ in inspect.getmembers(LLMPort, predicate=inspect.isfunction)}
    assert {"split_tasks","judge_sufficiency","generate_follow_up_question",
            "generate_plan","tag_plan"} <= names
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현** — `LLMPort` Protocol 에 spec §3.3 시그니처 4개 추가 (async, kwonly). `Turn`/`ParsedGoal`/`PlanDay` 는 `agents.todo_creation.state` 에서 import.
- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/protocols.py tests/agents/todo_creation/test_protocols.py
git commit -m "feat(todo): extend LLMPort with 4 multi-turn methods"
```

---

## Phase B — Multi-turn Nodes

character_creation 의 노드 패턴 (`async (state, config)`, state diff 또는 `Command` 반환). `RetryPolicy` 는 그래프 등록 시점 부여 (Task C2).

### Task B1: multi_validate_node

**Files:** Create `agents/todo_creation/multi_turn/nodes/validate.py`; Test `tests/agents/todo_creation/multi_turn/nodes/test_validate.py`.

- [ ] **Step 1: 실패 테스트**

```python
import pytest
from datetime import date, datetime, timezone
from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.multi_turn.nodes.validate import multi_validate_node

def _state(message: str) -> dict:
    return {"mode":"multi","user_id":"u1","message":message,
            "today":date(2026,5,25),
            "now":datetime(2026,5,25,tzinfo=timezone.utc),
            "history":[]}

@pytest.mark.asyncio
async def test_600_ok():
    out = await multi_validate_node(_state("가"*600), {})
    assert out["history"][-1] == {"role":"user","content":"가"*600}

@pytest.mark.asyncio
async def test_601_rejected():
    with pytest.raises(ValidationError):
        await multi_validate_node(_state("가"*601), {})

@pytest.mark.asyncio
async def test_empty_rejected():
    with pytest.raises(ValidationError):
        await multi_validate_node(_state(""), {})

@pytest.mark.asyncio
async def test_whitespace_rejected():
    with pytest.raises(ValidationError):
        await multi_validate_node(_state("   "), {})

@pytest.mark.asyncio
async def test_korean_ratio_threshold_ok():
    out = await multi_validate_node(_state("안녕하세요hello"), {})
    assert "history" in out

@pytest.mark.asyncio
async def test_no_korean_rejected():
    with pytest.raises(ValidationError):
        await multi_validate_node(_state("hello world only english"), {})

@pytest.mark.asyncio
async def test_history_appended_to_prior():
    s = _state("두번째")
    s["history"] = [{"role":"user","content":"첫번째"},
                    {"role":"assistant","content":"질문"}]
    out = await multi_validate_node(s, {})
    assert len(out["history"]) == 3
    assert out["history"][-1] == {"role":"user","content":"두번째"}
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현**

```python
from agents.todo_creation.exceptions import ValidationError

def _korean_syllable_ratio(text: str) -> float:
    """U+AC00–U+D7A3 ratio (공백·숫자 제외)."""
    chars = [c for c in text if not c.isspace() and not c.isdigit()]
    if not chars:
        return 0.0
    h = sum(1 for c in chars if 0xAC00 <= ord(c) <= 0xD7A3)
    return h / len(chars)

async def multi_validate_node(state, config):
    msg = state.get("message", "")
    if not msg or not msg.strip():
        raise ValidationError("multi_validate: empty message")
    if len(msg) > 600:
        raise ValidationError(f"multi_validate: length {len(msg)} > 600")
    if _korean_syllable_ratio(msg) < 0.5:
        raise ValidationError("multi_validate: korean syllable ratio < 0.5")
    return {"history": state.get("history", []) + [{"role":"user","content":msg}]}
```

- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/multi_turn/nodes/validate.py tests/agents/todo_creation/multi_turn/nodes/test_validate.py
git commit -m "feat(todo): add multi_validate (≤600, korean ratio 0.5)"
```

---

### Task B2: planner_node

**Files:** Create `agents/todo_creation/multi_turn/nodes/planner.py`; Test `tests/agents/todo_creation/multi_turn/nodes/test_planner.py`.

- [ ] **Step 1: 실패 테스트**

```python
import pytest
from unittest.mock import AsyncMock
from langgraph.types import Command
from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.multi_turn.nodes.planner import planner_node

def _state(): return {"history":[{"role":"user","content":"내일 토익"}], "message":"내일 토익"}
def _config(llm): return {"configurable":{"ports": type("P",(),{"llm":llm})()}}

@pytest.mark.asyncio
async def test_sufficient_goes_to_plan_generator():
    llm = AsyncMock(); llm.judge_sufficiency = AsyncMock(return_value=(True,[],{"goal_text":"토익 800"}))
    cmd = await planner_node(_state(), _config(llm))
    assert isinstance(cmd, Command); assert cmd.goto == "plan_generator"
    assert cmd.update["sufficiency"] is True
    assert cmd.update["parsed_goal"] == {"goal_text":"토익 800"}

@pytest.mark.asyncio
async def test_insufficient_goes_to_follow_up():
    llm = AsyncMock(); llm.judge_sufficiency = AsyncMock(return_value=(False,["목표 점수"],{}))
    cmd = await planner_node(_state(), _config(llm))
    assert cmd.goto == "follow_up"
    assert cmd.update["missing_aspects"] == ["목표 점수"]

@pytest.mark.asyncio
async def test_llm_output_error_propagates():
    llm = AsyncMock(); llm.judge_sufficiency = AsyncMock(side_effect=LLMOutputError("schema"))
    with pytest.raises(LLMOutputError):
        await planner_node(_state(), _config(llm))
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현**

```python
from langgraph.types import Command

async def planner_node(state, config):
    llm = config["configurable"]["ports"].llm
    sufficient, missing, parsed = await llm.judge_sufficiency(
        history=state.get("history", []),
        message=state.get("message", ""),
        today=state.get("today"),
    )
    return Command(
        goto="plan_generator" if sufficient else "follow_up",
        update={
            "sufficiency": sufficient,
            "missing_aspects": list(missing),
            "parsed_goal": dict(parsed) if parsed else None,
        },
    )
```

- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/multi_turn/nodes/planner.py tests/agents/todo_creation/multi_turn/nodes/test_planner.py
git commit -m "feat(todo): add planner node (sufficiency Command)"
```

---

### Task B3: follow_up_node (interrupt)

**Files:** Create `agents/todo_creation/multi_turn/nodes/follow_up.py`; Test `tests/agents/todo_creation/multi_turn/nodes/test_follow_up.py`.

- [ ] **Step 1: 실패 테스트**

```python
import pytest
from unittest.mock import AsyncMock, patch
from agents.todo_creation.multi_turn.nodes.follow_up import follow_up_node

def _state(): return {"history":[{"role":"user","content":"내일 시험"}],
                       "missing_aspects":["목표 점수"]}
def _config(llm): return {"configurable":{"ports": type("P",(),{"llm":llm})()}}

@pytest.mark.asyncio
async def test_calls_llm_and_interrupts():
    llm = AsyncMock(); llm.generate_follow_up_question = AsyncMock(return_value="목표 점수는?")
    with patch("agents.todo_creation.multi_turn.nodes.follow_up.interrupt", return_value="800점"):
        out = await follow_up_node(_state(), _config(llm))
    assert out["follow_up_question"] == "목표 점수는?"
    assert out["history"][-2:] == [
        {"role":"assistant","content":"목표 점수는?"},
        {"role":"user","content":"800점"},
    ]
    llm.generate_follow_up_question.assert_awaited_once_with(
        missing_aspects=["목표 점수"], history=[{"role":"user","content":"내일 시험"}],
    )
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현** — spec §2.2 의사코드

```python
from langgraph.types import interrupt

async def follow_up_node(state, config):
    ports = config["configurable"]["ports"]
    question = await ports.llm.generate_follow_up_question(
        missing_aspects=state.get("missing_aspects", []),
        history=state.get("history", []),
    )
    user_answer = interrupt(question)
    return {
        "follow_up_question": question,
        "history": state.get("history", []) + [
            {"role":"assistant","content":question},
            {"role":"user","content":user_answer},
        ],
    }
```

- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/multi_turn/nodes/follow_up.py tests/agents/todo_creation/multi_turn/nodes/test_follow_up.py
git commit -m "feat(todo): add follow_up node with interrupt-based resume"
```

---

### Task B4: plan_generator_node (C3 보장)

**Files:** Create `agents/todo_creation/multi_turn/nodes/plan_generator.py`; Test `tests/agents/todo_creation/multi_turn/nodes/test_plan_generator.py`.

- [ ] **Step 1: 실패 테스트**

```python
import pytest
from datetime import date
from unittest.mock import AsyncMock
from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.multi_turn.nodes.plan_generator import plan_generator_node

def _state(): return {"today":date(2026,5,25), "parsed_goal":{"goal_text":"토익 800"}}
def _config(llm): return {"configurable":{"ports": type("P",(),{"llm":llm})()}}

@pytest.mark.asyncio
async def test_ok():
    llm = AsyncMock(); llm.generate_plan = AsyncMock(return_value=("요약",[{"date":date(2026,5,25),"tasks":[]}]))
    out = await plan_generator_node(_state(), _config(llm))
    assert out["summary_text"] == "요약"; assert len(out["plan"]) == 1

@pytest.mark.asyncio
async def test_c3_violation_regenerates():
    llm = AsyncMock()
    llm.generate_plan = AsyncMock(side_effect=[
        ("가"*1501, [{"date":date(2026,5,25),"tasks":[]}]),
        ("가"*1000, [{"date":date(2026,5,25),"tasks":[]}]),
    ])
    out = await plan_generator_node(_state(), _config(llm))
    assert out["summary_text"] == "가"*1000
    assert llm.generate_plan.await_count == 2

@pytest.mark.asyncio
async def test_c3_violation_twice_truncates():
    llm = AsyncMock()
    llm.generate_plan = AsyncMock(return_value=("가"*1600, [{"date":date(2026,5,25),"tasks":[]}]))
    out = await plan_generator_node(_state(), _config(llm))
    assert len(out["summary_text"]) == 1500

@pytest.mark.asyncio
async def test_empty_plan_raises():
    llm = AsyncMock(); llm.generate_plan = AsyncMock(return_value=("요약",[]))
    with pytest.raises(LLMOutputError):
        await plan_generator_node(_state(), _config(llm))
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현**

```python
import logging
from agents.todo_creation.exceptions import LLMOutputError

log = logging.getLogger(__name__)
_C3_MAX = 1500

async def plan_generator_node(state, config):
    llm = config["configurable"]["ports"].llm
    parsed_goal = state.get("parsed_goal") or {}
    today = state.get("today")
    summary, days = await llm.generate_plan(parsed_goal=parsed_goal, today=today)
    if not days:
        raise LLMOutputError("plan: empty days")
    if len(summary) > _C3_MAX:
        log.warning("plan_generator: C3 violation (%d), regenerating", len(summary))
        summary, days = await llm.generate_plan(parsed_goal=parsed_goal, today=today)
        if not days:
            raise LLMOutputError("plan: empty days on regenerate")
        if len(summary) > _C3_MAX:
            log.warning("plan_generator: C3 still violated (%d), truncating", len(summary))
            summary = summary[:_C3_MAX]
    return {"summary_text": summary, "plan": days}
```

- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/multi_turn/nodes/plan_generator.py tests/agents/todo_creation/multi_turn/nodes/test_plan_generator.py
git commit -m "feat(todo): add plan_generator with C3 regenerate+truncate"
```

---

### Task B5: tagger_node (silent degrade)

**Files:** Create `agents/todo_creation/multi_turn/nodes/tagger.py`; Test `tests/agents/todo_creation/multi_turn/nodes/test_tagger.py`.

- [ ] **Step 1: 실패 테스트**

```python
import pytest
from datetime import date
from unittest.mock import AsyncMock
from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.multi_turn.nodes.tagger import tagger_node

def _state(): return {
    "plan":[{"date":date(2026,5,25),
             "tasks":[{"title":"단어 30","due_date":date(2026,5,25),"time_hint":None,"tags":[]}]}],
    "parsed_goal":{"goal_text":"토익 800"},
}
def _config(llm): return {"configurable":{"ports": type("P",(),{"llm":llm})()}}

@pytest.mark.asyncio
async def test_ok():
    llm = AsyncMock()
    tagged = [{"date":date(2026,5,25),
               "tasks":[{"title":"단어 30","due_date":date(2026,5,25),"time_hint":None,"tags":["토익"]}]}]
    llm.tag_plan = AsyncMock(return_value=tagged)
    out = await tagger_node(_state(), _config(llm))
    assert out["plan"][0]["tasks"][0]["tags"] == ["토익"]

@pytest.mark.asyncio
async def test_failure_degrades(caplog):
    llm = AsyncMock(); llm.tag_plan = AsyncMock(side_effect=LLMFailedError("network"))
    out = await tagger_node(_state(), _config(llm))
    assert out["plan"][0]["tasks"][0]["tags"] == []
    assert any("tagger" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현**

```python
import logging
log = logging.getLogger(__name__)

async def tagger_node(state, config):
    llm = config["configurable"]["ports"].llm
    plan = state.get("plan") or []
    parsed_goal = state.get("parsed_goal") or {}
    try:
        tagged = await llm.tag_plan(plan=plan, parsed_goal=parsed_goal)
        return {"plan": tagged}
    except Exception as exc:
        log.warning("tagger: degrade to empty tags: %s", exc)
        degraded = [
            {**day, "tasks":[{**t, "tags":[]} for t in day.get("tasks", [])]}
            for day in plan
        ]
        return {"plan": degraded}
```

- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/multi_turn/nodes/tagger.py tests/agents/todo_creation/multi_turn/nodes/test_tagger.py
git commit -m "feat(todo): add tagger with silent degrade on LLM failure"
```

---

## Phase C — Entry + Graph + Pipeline

### Task C1: entry_node

**Files:** Create `agents/todo_creation/nodes/entry.py`; Test `tests/agents/todo_creation/nodes/test_entry.py`.

- [ ] **Step 1: 실패 테스트**

```python
import pytest
from langgraph.types import Command
from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.nodes.entry import entry_node

@pytest.mark.asyncio
async def test_single():
    cmd = await entry_node({"mode":"single"}, {})
    assert isinstance(cmd, Command) and cmd.goto == "single_validate"

@pytest.mark.asyncio
async def test_multi():
    cmd = await entry_node({"mode":"multi"}, {})
    assert cmd.goto == "multi_validate"

@pytest.mark.asyncio
async def test_missing_raises():
    with pytest.raises(ValidationError):
        await entry_node({}, {})

@pytest.mark.asyncio
async def test_invalid_raises():
    with pytest.raises(ValidationError):
        await entry_node({"mode":"other"}, {})
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현**

```python
from langgraph.types import Command
from agents.todo_creation.exceptions import ValidationError

async def entry_node(state, config):
    mode = state.get("mode")
    if mode == "single": return Command(goto="single_validate")
    if mode == "multi":  return Command(goto="multi_validate")
    raise ValidationError(f"entry: invalid mode {mode!r}")
```

- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/nodes/entry.py tests/agents/todo_creation/nodes/test_entry.py
git commit -m "feat(todo): add entry node for single/multi mode branching"
```

---

### Task C2: graph.py (build_generate_graph)

**Files:** Create `agents/todo_creation/graph.py`; Test `tests/agents/todo_creation/test_graph.py` (smoke).

- [ ] **Step 1: 실패 테스트**

```python
from langgraph.checkpoint.memory import MemorySaver
from agents.todo_creation.graph import build_generate_graph

def test_compiles():
    g = build_generate_graph(checkpointer=MemorySaver())
    assert g is not None

def test_has_required_nodes():
    g = build_generate_graph(checkpointer=MemorySaver())
    names = set(g.get_graph().nodes.keys())
    required = {"entry","single_validate","task_splitter","date_router",
                "multi_validate","planner","follow_up","plan_generator","tagger"}
    assert required <= names
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현**

```python
from langgraph.graph import END, START, StateGraph
from langgraph.pregel.retry import RetryPolicy

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.state import GenerateState
from agents.todo_creation.nodes.entry import entry_node
from agents.todo_creation.single_turn.nodes.validate import validate_node as single_validate_node
from agents.todo_creation.single_turn.nodes.task_splitter import task_splitter_node
from agents.todo_creation.single_turn.nodes.date_router import date_router_node
from agents.todo_creation.multi_turn.nodes.validate import multi_validate_node
from agents.todo_creation.multi_turn.nodes.planner import planner_node
from agents.todo_creation.multi_turn.nodes.follow_up import follow_up_node
from agents.todo_creation.multi_turn.nodes.plan_generator import plan_generator_node
from agents.todo_creation.multi_turn.nodes.tagger import tagger_node


_llm_retry = RetryPolicy(max_attempts=3, retry_on=(LLMFailedError,))
_short_retry = RetryPolicy(max_attempts=2, retry_on=(LLMFailedError,))


def build_generate_graph(checkpointer):
    g = StateGraph(GenerateState)
    g.add_node("entry", entry_node, destinations=("single_validate","multi_validate"))
    g.add_node("single_validate", single_validate_node)
    g.add_node("task_splitter", task_splitter_node, retry=_llm_retry)
    g.add_node("date_router", date_router_node)
    g.add_node("multi_validate", multi_validate_node)
    g.add_node("planner", planner_node, retry=_llm_retry,
               destinations=("follow_up","plan_generator"))
    g.add_node("follow_up", follow_up_node, retry=_short_retry)
    g.add_node("plan_generator", plan_generator_node, retry=_llm_retry)
    g.add_node("tagger", tagger_node, retry=_short_retry)

    g.add_edge(START, "entry")
    g.add_edge("single_validate", "task_splitter")
    g.add_edge("task_splitter", "date_router")
    g.add_edge("multi_validate", "planner")
    g.add_edge("follow_up", "planner")
    g.add_edge("plan_generator", "tagger")
    g.add_edge("tagger", "date_router")
    g.add_edge("date_router", END)
    return g.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/graph.py tests/agents/todo_creation/test_graph.py
git commit -m "feat(todo): build unified generate_graph with checkpointer"
```

---

### Task C3: pipeline.py (run + thread lifecycle)

**Files:** Create `agents/todo_creation/pipeline.py`; Test `tests/agents/todo_creation/test_pipeline.py` (smoke).

- [ ] **Step 1: 실패 테스트**

```python
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from agents.todo_creation.schemas import SingleGenerateInput, GenerateResult
from agents.todo_creation.pipeline import run, GeneratePorts
from agents.todo_creation.state import PlanDay  # noqa
from agents.todo_creation.schemas import TaskCandidate

@pytest.fixture
def now(): return datetime(2026,5,25,tzinfo=timezone.utc)

@pytest.mark.asyncio
async def test_single_returns_generate_result(now):
    llm = AsyncMock()
    llm.split_tasks = AsyncMock(return_value=[
        TaskCandidate(title="x", due_date=date(2026,5,25), time_hint=None, tags=[])
    ])
    ports = GeneratePorts(llm=llm)
    inp = SingleGenerateInput(user_id="u1", prompt="오늘 코테 1개", today=date(2026,5,25))
    out = await run(inp, ports=ports, now=now)
    assert isinstance(out, GenerateResult)
    assert out.thread_id
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현**

```python
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agents.todo_creation.exceptions import ThreadNotFoundError
from agents.todo_creation.graph import build_generate_graph
from agents.todo_creation.protocols import LLMPort
from agents.todo_creation.schemas import (
    FollowUpResult, GenerateInput, GenerateResult, MultiGenerateInput,
    SingleGenerateInput, TaskCandidate, TurnResult,
)


@dataclass
class GeneratePorts:
    llm: LLMPort


_CHECKPOINTER = MemorySaver()
_GRAPH = build_generate_graph(checkpointer=_CHECKPOINTER)


def _initial_state(inp, now: datetime) -> dict[str, Any]:
    if isinstance(inp, SingleGenerateInput):
        return {"mode":"single","user_id":inp.user_id,"today":inp.today,"now":now,
                "prompt":inp.prompt}
    return {"mode":"multi","user_id":inp.user_id,"today":inp.today,"now":now,
            "message":inp.message,"history":[]}


def _to_task_candidate(t):
    return t if isinstance(t, TaskCandidate) else TaskCandidate(**t)


async def run(inp: GenerateInput, *, ports: GeneratePorts, now: datetime) -> TurnResult:
    config: dict[str, Any] = {"configurable":{"ports":ports,"now":now}}

    is_resume = isinstance(inp, MultiGenerateInput) and inp.thread_id is not None
    if is_resume:
        thread_id = inp.thread_id
        config["configurable"]["thread_id"] = thread_id
        snap = await _CHECKPOINTER.aget({"configurable":{"thread_id":thread_id}})
        if snap is None:
            raise ThreadNotFoundError(f"thread {thread_id} not found")
        result = await _GRAPH.ainvoke(Command(resume=inp.message), config=config)
    else:
        thread_id = str(uuid.uuid4())
        config["configurable"]["thread_id"] = thread_id
        result = await _GRAPH.ainvoke(_initial_state(inp, now), config=config)

    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if interrupts:
        first = interrupts[0]
        out = FollowUpResult(
            thread_id=thread_id,
            question=getattr(first, "value", str(first)),
            missing_aspects=result.get("missing_aspects", []),
        )
    else:
        out = GenerateResult(
            thread_id=thread_id,
            todos=[_to_task_candidate(t) for t in result.get("todos", [])],
            calendar_events=[_to_task_candidate(t) for t in result.get("calendar_events", [])],
            summary_text=result.get("summary_text"),
        )

    if isinstance(inp, SingleGenerateInput):
        await _CHECKPOINTER.adelete_thread(thread_id)
    return out
```

- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add agents/todo_creation/pipeline.py tests/agents/todo_creation/test_pipeline.py
git commit -m "feat(todo): add unified pipeline.run with thread lifecycle"
```

---

## Phase D — Adapter Unification

### Task D1: openai_llm.py 4 메서드 흡수 + 테스트 통합

**Files:** Modify `adapters/todo_creation/openai_llm.py`, `tests/adapters/todo_creation/test_openai_llm.py`.

- [ ] **Step 1: 기존 `tests/adapters/todo_creation/test_openai_multi_turn.py` 의 4 메서드 테스트를 그대로 `test_openai_llm.py` 끝에 복사** (이름·assert 변경 없음, import 만 단일 `OpenAILLM` 으로).
- [ ] **Step 2: 실행해서 실패 확인** — Expected: AttributeError (`judge_sufficiency` 등 미정의).
- [ ] **Step 3: 구현** — `OpenAILLM` 클래스에 4 async 메서드 추가. 본문은 기존 `adapters/todo_creation/openai_multi_turn.py` 의 동명 메서드를 그대로 이식 (`beta.chat.completions.parse` 호출, structured output 옵션 동일). 프롬프트 문자열도 그대로.
- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add adapters/todo_creation/openai_llm.py tests/adapters/todo_creation/test_openai_llm.py
git commit -m "feat(todo): absorb 4 multi-turn methods into OpenAILLM"
```

---

### Task D2: fake_llm.py 4 메서드 흡수

**Files:** Modify `adapters/todo_creation/fake_llm.py`, `tests/adapters/todo_creation/test_fake_llm.py`.

- [ ] **Step 1: 실패 테스트**

```python
import pytest
from datetime import date
from agents.todo_creation.exceptions import LLMFailedError
from adapters.todo_creation.fake_llm import FakeLLM

@pytest.mark.asyncio
async def test_judge_sufficiency_queue():
    llm = FakeLLM(judge_sufficiency_queue=[(False,["x"],{}), (True,[],{"goal_text":"g"})])
    r1 = await llm.judge_sufficiency(history=[], message="x", today=date(2026,5,25))
    r2 = await llm.judge_sufficiency(history=[], message="x", today=date(2026,5,25))
    assert r1[0] is False and r2[0] is True

@pytest.mark.asyncio
async def test_follow_up_question():
    llm = FakeLLM(follow_up_questions=["목표 점수는?"])
    q = await llm.generate_follow_up_question(missing_aspects=[], history=[])
    assert q == "목표 점수는?"

@pytest.mark.asyncio
async def test_generate_plan():
    llm = FakeLLM(plans=[("요약",[{"date":date(2026,5,25),"tasks":[]}])])
    s, d = await llm.generate_plan(parsed_goal={}, today=date(2026,5,25))
    assert s == "요약" and len(d) == 1

@pytest.mark.asyncio
async def test_tag_plan():
    tagged = [{"date":date(2026,5,25),
               "tasks":[{"title":"x","due_date":date(2026,5,25),"time_hint":None,"tags":["t"]}]}]
    llm = FakeLLM(tagged_plans=[tagged])
    out = await llm.tag_plan(plan=[], parsed_goal={})
    assert out == tagged

@pytest.mark.asyncio
async def test_tag_plan_failure_simulation():
    llm = FakeLLM(tag_plan_fail=True)
    with pytest.raises(LLMFailedError):
        await llm.tag_plan(plan=[], parsed_goal={})
```

- [ ] **Step 2: 실패 확인**.
- [ ] **Step 3: 구현** — `FakeLLM.__init__` 에 4 큐/플래그 인자 추가 (`judge_sufficiency_queue`, `follow_up_questions`, `plans`, `tagged_plans`, `tag_plan_fail`). 4 async 메서드 본문은 기존 `fake_multi_turn_llm.py` 의 동명 로직 이식.
- [ ] **Step 4: 통과 확인**.
- [ ] **Step 5: commit**

```bash
git add adapters/todo_creation/fake_llm.py tests/adapters/todo_creation/test_fake_llm.py
git commit -m "feat(todo): absorb 4 multi-turn methods into FakeLLM queue pattern"
```

---

### Task D3: multi-turn-only 어댑터 삭제 + 호출처 정리

**Files to delete:** `adapters/todo_creation/openai_multi_turn.py`, `adapters/todo_creation/fake_multi_turn_llm.py`, `tests/adapters/todo_creation/test_openai_multi_turn.py`.

- [ ] **Step 1: 호출처 grep**

```bash
grep -rn "openai_multi_turn\|fake_multi_turn_llm\|FakeMultiTurnLLM\|OpenAIMultiTurn" \
  --include="*.py" agents/ adapters/ tests/ streamlit_app/
```

- [ ] **Step 2: 호출처 import 교체** — 모두 단일 `OpenAILLM` / `FakeLLM` 으로. 생성자 인자가 다르면 새 큐 패턴(`judge_sufficiency_queue=...`) 으로 변환.

- [ ] **Step 3: 파일 삭제**

```bash
git rm adapters/todo_creation/openai_multi_turn.py \
       adapters/todo_creation/fake_multi_turn_llm.py \
       tests/adapters/todo_creation/test_openai_multi_turn.py
```

- [ ] **Step 4: 전체 테스트 확인**

```bash
uv run pytest --cov=agents/todo_creation --cov-report=term-missing 2>&1 | tail -50
```
Expected: 통과, multi-turn 어댑터 import 에러 없음.

- [ ] **Step 5: commit**

```bash
git add -u
git commit -m "refactor(todo): remove multi-turn-only adapters after absorption"
```

---

## Phase E — Integration Scenarios

각 시나리오는 spec §6.2 기반. `build_generate_graph(checkpointer=MemorySaver())` + `FakeLLM` (Task D2 흡수 후) + `pipeline.run` (Task C3) 으로 검증.

### Task E1: single happy path

**File:** `tests/agents/todo_creation/test_graph.py` (확장).

- [ ] **Step 1: 테스트 추가**

```python
import pytest
from datetime import date, datetime, timezone
from agents.todo_creation.pipeline import run, GeneratePorts
from agents.todo_creation.schemas import SingleGenerateInput, GenerateResult, TaskCandidate
from adapters.todo_creation.fake_llm import FakeLLM

@pytest.fixture
def now(): return datetime(2026,5,25,tzinfo=timezone.utc)

@pytest.mark.asyncio
async def test_single_today_only(now):
    llm = FakeLLM(responses=[
        [TaskCandidate(title="코테 1회", due_date=date(2026,5,25), time_hint=None, tags=[])]
    ])
    out = await run(SingleGenerateInput(user_id="u1", prompt="오늘 코테 1개", today=date(2026,5,25)),
                    ports=GeneratePorts(llm=llm), now=now)
    assert isinstance(out, GenerateResult)
    assert len(out.todos) == 1 and len(out.calendar_events) == 0

@pytest.mark.asyncio
async def test_single_mixed(now):
    llm = FakeLLM(responses=[[
        TaskCandidate(title="오늘", due_date=date(2026,5,25), time_hint=None, tags=[]),
        TaskCandidate(title="미래", due_date=date(2026,5,28), time_hint=None, tags=[]),
    ]])
    out = await run(SingleGenerateInput(user_id="u1", prompt="오늘과 미래", today=date(2026,5,25)),
                    ports=GeneratePorts(llm=llm), now=now)
    assert len(out.todos) == 1 and len(out.calendar_events) == 1
```

- [ ] **Step 2~4: 실행·통과 확인**.
- [ ] **Step 5: commit**

```bash
git add tests/agents/todo_creation/test_graph.py
git commit -m "test(todo): single happy paths through unified graph"
```

---

### Task E2: multi follow_up loop (2 turn)

- [ ] **Step 1: 테스트 추가**

```python
from agents.todo_creation.schemas import MultiGenerateInput, FollowUpResult, GenerateResult

@pytest.mark.asyncio
async def test_multi_two_turns(now):
    llm = FakeLLM(
        judge_sufficiency_queue=[
            (False, ["목표 점수"], {}),
            (True,  [], {"goal_text":"토익 800"}),
        ],
        follow_up_questions=["목표 점수는?"],
        plans=[("요약", [{"date":date(2026,5,25),
                          "tasks":[{"title":"단어 30","due_date":date(2026,5,25),
                                    "time_hint":None,"tags":[]}]}])],
        tagged_plans=[[{"date":date(2026,5,25),
                        "tasks":[{"title":"단어 30","due_date":date(2026,5,25),
                                  "time_hint":None,"tags":["토익"]}]}]],
    )
    ports = GeneratePorts(llm=llm)

    t1 = await run(MultiGenerateInput(user_id="u1", message="내일 토익 시험",
                                       today=date(2026,5,25)),
                   ports=ports, now=now)
    assert isinstance(t1, FollowUpResult); assert t1.question == "목표 점수는?"
    tid = t1.thread_id

    t2 = await run(MultiGenerateInput(user_id="u1", message="800점",
                                       today=date(2026,5,25), thread_id=tid),
                   ports=ports, now=now)
    assert isinstance(t2, GenerateResult); assert t2.thread_id == tid
    assert t2.todos[0].tags == ["토익"]
    assert (t2.summary_text or "") and len(t2.summary_text) <= 1500
```

- [ ] **Step 2~4: 실행·통과 확인**.
- [ ] **Step 5: commit**

```bash
git commit -am "test(todo): multi two-turn follow_up via interrupt+resume"
```

---

### Task E3: multi N turn — turn 5 sufficient

- [ ] **Step 1: 테스트 추가** — `judge_sufficiency_queue=[False*4, True]`, `follow_up_questions=["q1","q2","q3","q4"]`, plan/tagged_plan 1개. turn 1~4 각각 `FollowUpResult` 반환, turn 5 `GenerateResult`. `_CHECKPOINTER.aget(...)` 로 turn 5 후 `history` 길이가 `9` 임을 확인 (turn N → 2N-1).
- [ ] **Step 2~4: 실행·통과 확인**.
- [ ] **Step 5: commit**

```bash
git commit -am "test(todo): multi 5-turn loop until sufficient with history length"
```

---

### Task E4: multi C3 violation 시나리오

- [ ] **Step 1: 테스트 추가** — (1) `plans=[("가"*1501, days), ("가"*1000, days)]` → 재생성 후 `len(summary_text)==1000`. (2) `plans=[("가"*1600, days)]` (한 응답을 반복적으로 반환하도록 FakeLLM 큐 다시 채우거나 queue 길이 2로) → `len(summary_text)==1500`.
- [ ] **Step 2~4: 실행·통과 확인**.
- [ ] **Step 5: commit**

```bash
git commit -am "test(todo): plan_generator C3 regenerate and truncate scenarios"
```

---

### Task E5: multi tagger silent degrade

- [ ] **Step 1: 테스트 추가** — `FakeLLM(... tag_plan_fail=True ...)` → `GenerateResult` 정상 반환, 모든 `todos`/`calendar_events` 의 `tags == []`.
- [ ] **Step 2~4: 실행·통과 확인**.
- [ ] **Step 5: commit**

```bash
git commit -am "test(todo): tagger failure degrades to empty tags"
```

---

### Task E6: thread isolation + ThreadNotFoundError

- [ ] **Step 1: 테스트 추가**

```python
from agents.todo_creation.exceptions import ThreadNotFoundError

@pytest.mark.asyncio
async def test_unknown_thread_raises(now):
    llm = FakeLLM()
    with pytest.raises(ThreadNotFoundError):
        await run(MultiGenerateInput(user_id="u1", message="안녕",
                                      today=date(2026,5,25), thread_id="ghost"),
                  ports=GeneratePorts(llm=llm), now=now)

@pytest.mark.asyncio
async def test_two_threads_isolated(now):
    llm_a = FakeLLM(judge_sufficiency_queue=[(False,["x"],{})], follow_up_questions=["A?"])
    llm_b = FakeLLM(judge_sufficiency_queue=[(False,["y"],{})], follow_up_questions=["B?"])
    out_a = await run(MultiGenerateInput(user_id="u1", message="대화A", today=date(2026,5,25)),
                      ports=GeneratePorts(llm=llm_a), now=now)
    out_b = await run(MultiGenerateInput(user_id="u2", message="대화B", today=date(2026,5,25)),
                      ports=GeneratePorts(llm=llm_b), now=now)
    assert out_a.thread_id != out_b.thread_id
    assert out_a.question == "A?" and out_b.question == "B?"
```

- [ ] **Step 2~4: 실행·통과 확인**.
- [ ] **Step 5: commit**

```bash
git commit -am "test(todo): thread isolation and ThreadNotFoundError"
```

---

## Phase F — Migration & Cleanup

### Task F1: streamlit_app/app.py 통합 그래프 사용

- [ ] **Step 1: 호출처 grep**

```bash
grep -n "agents.todo_creation.single_turn\|single_turn.pipeline" streamlit_app/app.py
```

- [ ] **Step 2: import 교체** — `from agents.todo_creation.pipeline import run, GeneratePorts` + `from agents.todo_creation.schemas import SingleGenerateInput`. 호출은 `await run(SingleGenerateInput(user_id=..., prompt=..., today=...), ports=GeneratePorts(llm=...), now=datetime.now(tz))`.
- [ ] **Step 3: streamlit smoke**

```bash
uv run streamlit run streamlit_app/app.py --server.headless true &
sleep 3 && curl -s http://localhost:8501 > /dev/null && echo "ok"
kill %1
```

- [ ] **Step 4: commit**

```bash
git add streamlit_app/app.py
git commit -m "refactor(streamlit): use unified todo_creation.pipeline.run"
```

---

### Task F2: single_turn pipeline 제거

- [ ] **Step 1: 호출처 grep**

```bash
grep -rn "from agents.todo_creation.single_turn\.\(pipeline\|graph\|state\)" --include="*.py" .
```
Expected: graph.py 외 결과 없음 (graph.py 는 `single_turn.nodes.*` 만 import; pipeline/graph/state import 0).

- [ ] **Step 2: 삭제**

```bash
git rm agents/todo_creation/single_turn/pipeline.py \
       agents/todo_creation/single_turn/graph.py \
       agents/todo_creation/single_turn/state.py \
       tests/agents/todo_creation/single_turn/test_pipeline.py
```

- [ ] **Step 3: 전체 테스트 + cov**

```bash
uv run pytest --cov=agents/todo_creation --cov-report=term-missing 2>&1 | tail -50
```
Expected: 80%+, fail 없음.

- [ ] **Step 4: commit**

```bash
git add -u
git commit -m "refactor(todo): remove single_turn pipeline/graph/state (absorbed)"
```

---

### Task F3: CHANGELOG entry

- [ ] **Step 1: 항목 추가** — `CHANGELOG.md` 의 `Unreleased` 섹션:

```markdown
### Added
- `agents/todo_creation/` single/multi 통합 `generate_graph` (LangGraph checkpointer + interrupt(follow_up))
- `MultiGenerateInput`, `FollowUpResult`, `TurnResult` 스키마
- `LLMPort` 의 4 메서드 (`judge_sufficiency`, `generate_follow_up_question`, `generate_plan`, `tag_plan`)
- `ThreadNotFoundError` (4xx)

### Changed
- `commit_graph` 는 분리 유지. 클라가 `GenerateResult` 받아 `/todos/commit` 별도 호출
- `single_turn/{pipeline,graph,state}.py` 제거 (통합 그래프로 흡수)
- 이전 multi-only 부산물 `openai_multi_turn`, `fake_multi_turn_llm` 어댑터 → `OpenAILLM`·`FakeLLM` 으로 흡수·폐기
```

- [ ] **Step 2: commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record unified todo generate_graph migration"
```

---

### Task F4: architecture.mmd as-built 갱신

- [ ] **Step 1: 다이어그램 교체** — `docs/features/todo/architecture.mmd` 의 SINGLE/MULTI 서브그래프를 spec §2.1 통합 그래프로 (entry → single_validate / multi_validate, multi 의 planner ↔ follow_up loop, plan_generator → tagger, date_router fan-in).
- [ ] **Step 2: mermaid 렌더 확인** (VS Code preview 또는 mermaid live editor).
- [ ] **Step 3: commit**

```bash
git add docs/features/todo/architecture.mmd
git commit -m "docs(architecture): update todo MULTI subgraph to interrupt-based loop"
```

---

### Task F5: docs/features/todo/CLAUDE.md §4 갱신

- [ ] **Step 1: §4.5–§4.10 옆에 "구현 완료 — `agents/todo_creation/multi_turn/nodes/<...>.py`" 주석 추가**. §7 미결사항 표:
  - §7.2(세션 저장소) → "checkpointer/MemorySaver 사용, prod 인프라는 별도 PR"
  - 나머지는 그대로.
- [ ] **Step 2: commit**

```bash
git add docs/features/todo/CLAUDE.md
git commit -m "docs(todo): mark multi-turn nodes as implemented in feature guide"
```

---

## Final Verification

- [ ] **Step 1: 전체 pytest + cov**

```bash
uv run pytest --cov=agents/todo_creation --cov-report=term-missing 2>&1 | tail -50
```
Expected: agents/todo_creation 80%+, §6.2 12 시나리오 통과.

- [ ] **Step 2: ruff**

```bash
ruff check agents/todo_creation tests/agents/todo_creation adapters/todo_creation
```
Expected: clean.

- [ ] **Step 3: DoD 체크 (spec §9 17 항목)** — 모두 ✅.
- [ ] **Step 4: push** (사용자 명시 시).

---

## Self-Review

**Spec coverage:**
- §1 디렉토리 → Phase A·B·C·D 의 Create/Modify/Delete 일치
- §2.1 그래프 도식 → Task C2 `build_generate_graph`
- §2.2 follow_up 의사코드 → Task B3
- §3 스키마/state/포트 → Task A1·A3·A4
- §4 데이터 흐름 → Task C3 + Phase E 시나리오
- §5 에러 처리 → Task A2 (`ThreadNotFoundError`), Phase B 노드별 raise/degrade, Task C3 의 thread 검사
- §6.1 단위 / §6.2 통합 → Phase B / Phase E 매핑
- §7 마이그레이션 → Phase D·F
- §8 의도적 배제 → plan 다루지 않음 (의도적)
- §9 DoD 17 항목 → Final Verification §3 체크

**Placeholder scan:** "TBD"/"appropriate"/"similar to" 없음. D1·D2 의 "기존 본문 이식" 은 동명 메서드 시그니처 + 프롬프트 동일 명시.

**Type consistency:**
- `judge_sufficiency` 반환 `tuple[bool, list[str], ParsedGoal]` — A4·B2·D1·D2·E 일치
- `generate_plan` 반환 `tuple[str, list[PlanDay]]` — A4·B4·D1·D2·E 일치
- `tag_plan` 반환 `list[PlanDay]` — A4·B5·D1·D2·E 일치
- 노드 함수명: `entry_node`, `single_validate_node`, `task_splitter_node`, `date_router_node`, `multi_validate_node`, `planner_node`, `follow_up_node`, `plan_generator_node`, `tagger_node` — C2 graph 등록명과 일관.
