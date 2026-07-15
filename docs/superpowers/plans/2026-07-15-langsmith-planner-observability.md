# LangSmith Planner Observability & Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LangSmith 관찰·평가를 피드백 루프로 삼아, RunPod에 떠 있는 planner(**EXAONE-3.5 base + planner LoRA**)의 `_prompts.py` 프롬프트와 그래프 구조를 고쳐 출력을 개선한다. Task 1–6은 그 피드백 루프(관찰·평가·before/after 비교)를 구축하고, Task 7이 개선 루프다.

**Architecture:** LangGraph 노드는 env만 켜면 자동 추적된다. RunPod LLM 호출은 커스텀 `complete_raw()` 경계 하나에 `@traceable`을 붙여 트리에 노출한다. 평가는 `llm_evaluation/langsmith/`에 데이터셋+평가자(휴리스틱 5 + judge 재사용 2)를 두고, 라이브 RunPod를 때리는 target으로 `aevaluate()`를 돌린다. 개선은 baseline 평가 → 프롬프트/구조 수정 → 재평가 → `compare.py` before/after의 반복.

**베이스 주의:** 서빙은 **EXAONE**(Qwen 아님). 어댑터 클래스 이름 `QwenLLM`/`RunPodQwenLLM`은 레거시 명칭일 뿐 실제 모델은 EXAONE-3.5-7.8B + planner LoRA. 프롬프트는 EXAONE 출력 실측 기준으로 고친다.

**Tech Stack:** Python 3.12, LangGraph, langchain-core, langsmith SDK, Pydantic v2, pytest/anyio.

## Global Constraints

- 불변 패턴 유지, 기존 코드 변경 금지 원칙 — 새 파일 위주, 기존 파일은 추가만.
- `init_langsmith()`·`@traceable`는 키/플래그 없으면 **no-op**. 프로덕션 경로 절대 안 깨짐.
- LLM 에러 흐름(`LLMFailedError` + `RetryPolicy`) 불변 — 트레이싱이 예외를 삼키거나 변형하지 않음.
- 의존성 버전 핀: `langsmith>=0.1,<0.4` (langchain-core 0.3 호환).
- evaluator 코어는 순수 함수(LangSmith 객체 비의존) — canned dict로 유닛테스트 가능해야 함.
- 새 judge 모델 도입 금지 — 기존 `judge_sufficiency`만 재사용.

### 확정된 기존 인터페이스 (변경 금지, 그대로 소비)

- `agents.todo_creation.planner.pipeline.run(input: PlannerInput, *, ports: PlannerPorts, now: datetime) -> PlannerResult`
- `PlannerResult = Annotated[CandidatesResult | FollowUpResult | OutOfScopeResult, Field(discriminator="kind")]`
  - `CandidatesResult`: `kind="candidates"`, `thread_id: str`, `todos: list[TaskCandidate]`, `calendar_events: list[TaskCandidate]`, `summary_text: str | None`, `personalization_patch: dict | None`
  - `FollowUpResult`: `kind="follow_up"`, `thread_id: str`, `question: str(≤300)`, `missing_aspects: list[str]`
  - `OutOfScopeResult`: `kind="out_of_scope"`, `thread_id: str`, `message: str`
  - `TaskCandidate`: `title: str(1..20)`, `due_date: date`, `tags: list[str]`
- `PlannerInput`: `user_id: str`, `message: str(1..600)`, `today: date`, `thread_id: str | None`, `user_profile_memory: dict | None`
- 멀티턴: 같은 `thread_id`로 `run()` 재호출 시 follow_up interrupt에서 이어짐(`Command(resume=message)`).
- `api.config.AppConfig.from_env() -> AppConfig`
- `api.deps.build_todo_planner_ports(cfg: AppConfig) -> PlannerPorts` (프로덕션과 동일한 RunPod ports 생성; `ports.llm`=planner, `ports.classifier`=base)
- judge: `ports.classifier.judge_sufficiency(*, history: list[Turn], message: str, today: date, user_profile_memory=None) -> tuple[bool, list[str], ParsedGoal]`, `Turn = {"role": "user"|"assistant", "content": str}`
- LLM 경계: `adapters/todo_creation/runpod_llm.py::RunPodQwenLLM.complete_raw(*, messages, label="qwen", temperature=None, guided_json=None) -> str`
- `api/main.py::create_app() -> FastAPI` (모듈 top에서 `load_dotenv()` 이미 호출됨)

---

## File Structure

- Create `agents/_shared/observability/langsmith.py` — `init_langsmith()`, `langsmith_enabled()`. init 진입점.
- Modify `agents/_shared/observability/__init__.py` — export 추가.
- Modify `api/main.py` — `create_app()`에서 `init_langsmith()` 호출.
- Modify `adapters/todo_creation/runpod_llm.py` — `complete_raw`에 `@traceable`.
- Modify `requirements-api.txt`, `pyproject.toml` — `langsmith` 의존성.
- Create `llm_evaluation/langsmith/__init__.py`
- Create `llm_evaluation/langsmith/evaluators.py` — 휴리스틱 5 + judge 팩토리 2.
- Create `llm_evaluation/langsmith/datasets/planner_cases.jsonl` — 시드 케이스(증분 가능).
- Create `llm_evaluation/langsmith/dataset.py` — jsonl 로드 + LangSmith 업로드(멱등).
- Create `llm_evaluation/langsmith/run_eval.py` — target + `aevaluate` 실행.
- Create tests: `tests/observability/test_langsmith_init.py`, `tests/llm_evaluation/test_evaluators.py`, `tests/llm_evaluation/test_judge_evaluators.py`, `tests/llm_evaluation/test_dataset.py`.

---

## Task 1: LangSmith 트레이싱 배선

**Files:**
- Create: `agents/_shared/observability/langsmith.py`
- Modify: `agents/_shared/observability/__init__.py`
- Modify: `api/main.py:31` (`create_app` 본문 시작)
- Modify: `adapters/todo_creation/runpod_llm.py` (`complete_raw`)
- Modify: `requirements-api.txt`, `pyproject.toml`
- Test: `tests/observability/test_langsmith_init.py`

**Interfaces:**
- Produces: `init_langsmith() -> bool` (활성 여부 반환), `langsmith_enabled() -> bool`.

- [ ] **Step 1: 의존성 추가**

`requirements-api.txt`에 한 줄 추가(기존 `langgraph>=...` 근처):
```
langsmith>=0.1,<0.4
```
`pyproject.toml`의 dependencies 배열에 추가:
```toml
    "langsmith>=0.1,<0.4",
```

- [ ] **Step 2: Write the failing test**

`tests/observability/test_langsmith_init.py`:
```python
import os
import pytest
from agents._shared.observability.langsmith import init_langsmith, langsmith_enabled


def _clear(monkeypatch):
    for k in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT"):
        monkeypatch.delenv(k, raising=False)


def test_disabled_without_key(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")  # 키 없음
    assert langsmith_enabled() is False
    assert init_langsmith() is False


def test_disabled_without_flag(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_x")  # 플래그 없음
    assert init_langsmith() is False


def test_enabled_sets_defaults(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_x")
    assert init_langsmith() is True
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://api.smith.langchain.com"
    assert os.environ["LANGSMITH_PROJECT"] == "mongle-planner"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/observability/test_langsmith_init.py -v`
Expected: FAIL (ModuleNotFoundError: langsmith init module)

- [ ] **Step 4: Write minimal implementation**

`agents/_shared/observability/langsmith.py`:
```python
from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def langsmith_enabled() -> bool:
    """LANGSMITH_TRACING 플래그가 켜져 있고 API 키가 있으면 True."""
    flag = os.environ.get("LANGSMITH_TRACING", "").strip().lower() in _TRUTHY
    has_key = bool(os.environ.get("LANGSMITH_API_KEY", "").strip())
    return flag and has_key


def init_langsmith() -> bool:
    """LangSmith 트레이싱을 켠다. 멱등, 키/플래그 없으면 no-op.

    langsmith SDK 와 langchain 은 LANGSMITH_* 환경변수를 직접 읽으므로
    여기서는 기본 endpoint/project 만 채워주고 활성 여부를 반환한다.
    """
    if not langsmith_enabled():
        return False
    os.environ.setdefault("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    os.environ.setdefault("LANGSMITH_PROJECT", "mongle-planner")
    return True
```

`agents/_shared/observability/__init__.py`에 추가:
```python
from agents._shared.observability.langsmith import init_langsmith, langsmith_enabled
```
그리고 `__all__` 리스트에 `"init_langsmith"`, `"langsmith_enabled"` 추가.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/observability/test_langsmith_init.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: create_app에서 호출**

`api/main.py`의 `create_app()` 본문 첫 줄에 삽입(`app = FastAPI(...)` 직전):
```python
def create_app() -> FastAPI:
    from agents._shared.observability import init_langsmith

    init_langsmith()
    app = FastAPI(title="Mongle AI Engine", lifespan=lifespan)
```

- [ ] **Step 7: complete_raw에 @traceable**

`adapters/todo_creation/runpod_llm.py` 상단 import에 추가:
```python
from langsmith import traceable
```
파일 상단(클래스 밖)에 self 제거 헬퍼 추가:
```python
def _drop_self(inputs: dict) -> dict:
    return {k: v for k, v in inputs.items() if k != "self"}
```
`RunPodQwenLLM.complete_raw` 정의 바로 위에 데코레이터 추가(시그니처·본문 불변):
```python
    @traceable(run_type="llm", name="runpod_llm", process_inputs=_drop_self)
    async def complete_raw(
        self,
        *,
        messages: list[dict[str, str]],
        label: str = "qwen",
        temperature: float | None = None,
        guided_json: dict | None = None,
    ) -> str:
```
`@traceable`은 `LANGSMITH_TRACING` 미설정 시 순수 pass-through(반환·예외 불변)라 프로덕션 안전.

- [ ] **Step 8: 회귀 확인 — 기존 planner 테스트 그린**

Run: `uv run pytest tests/agents/todo_creation/planner/ -q`
Expected: PASS (트레이싱 배선이 기존 거동 안 바꿈)

- [ ] **Step 9: Commit**

```bash
git add agents/_shared/observability/ api/main.py adapters/todo_creation/runpod_llm.py \
        requirements-api.txt pyproject.toml tests/observability/test_langsmith_init.py
git commit -m "feat: LangSmith 트레이싱 배선 (init + complete_raw @traceable)"
```

---

## Task 2: 휴리스틱 평가자 (순수 함수)

**Files:**
- Create: `llm_evaluation/langsmith/__init__.py` (빈 파일)
- Create: `llm_evaluation/langsmith/evaluators.py`
- Test: `tests/llm_evaluation/test_evaluators.py`

**Interfaces:**
- Consumes: `PlannerResult` 스키마(Global Constraints).
- Produces: 평가자 함수 `structure_valid`, `routing_correct`, `date_sanity`, `korean_only`, `frontend_contract` — 각각 `(outputs: dict, reference_outputs: dict, inputs: dict) -> dict`, 반환 `{"key": str, "score": int|None, "comment": str}`. `HEURISTIC_EVALUATORS: list` 로 묶어서 export.
- 규약: `outputs = {"kind": str, "result": dict}`, `reference_outputs = {"category": str, "expected_kind": str}`, `inputs = {"user_id","turns","today","user_profile_memory"}`.

- [ ] **Step 1: Write the failing test**

`tests/llm_evaluation/test_evaluators.py`:
```python
from llm_evaluation.langsmith.evaluators import (
    structure_valid, routing_correct, date_sanity, korean_only, frontend_contract,
)

_TODAY = "2026-07-15"


def _plan_out(todos):
    return {"kind": "candidates", "result": {
        "kind": "candidates", "thread_id": "t", "todos": todos,
        "calendar_events": [], "summary_text": "요약", "personalization_patch": None}}


def _todo(title="공부", due="2026-07-20", tags=None):
    return {"title": title, "due_date": due, "tags": tags or ["학습"]}


def _inputs(turns=None):
    return {"user_id": "u1", "turns": turns or ["수능 공부 계획"], "today": _TODAY,
            "user_profile_memory": None}


def test_structure_valid_pass():
    out = _plan_out([_todo()])
    assert structure_valid(out, {"expected_kind": "candidates"}, _inputs())["score"] == 1


def test_structure_valid_fail_bad_title():
    out = _plan_out([_todo(title="")])  # min_length=1 위반
    assert structure_valid(out, {"expected_kind": "candidates"}, _inputs())["score"] == 0


def test_routing_correct():
    out = {"kind": "follow_up", "result": {"kind": "follow_up", "thread_id": "t",
           "question": "언제까지?", "missing_aspects": ["deadline"]}}
    assert routing_correct(out, {"expected_kind": "follow_up"}, _inputs())["score"] == 1
    assert routing_correct(out, {"expected_kind": "candidates"}, _inputs())["score"] == 0


def test_date_sanity_past_due_fails():
    out = _plan_out([_todo(due="2026-07-01")])  # today 이전
    assert date_sanity(out, {}, _inputs())["score"] == 0
    out2 = _plan_out([_todo(due="2026-07-20")])
    assert date_sanity(out2, {}, _inputs())["score"] == 1


def test_korean_only_flags_foreign():
    out = _plan_out([_todo(title="勉強する")])  # 일본어/한자
    assert korean_only(out, {}, _inputs())["score"] == 0
    assert korean_only(_plan_out([_todo(title="공부하기")]), {}, _inputs())["score"] == 1


def test_frontend_contract_requires_render_fields():
    good = _plan_out([_todo()])
    assert frontend_contract(good, {}, _inputs())["score"] == 1
    bad = {"kind": "candidates", "result": {"kind": "candidates", "thread_id": "t"}}
    assert frontend_contract(bad, {}, _inputs())["score"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/llm_evaluation/test_evaluators.py -v`
Expected: FAIL (ModuleNotFoundError: evaluators)

- [ ] **Step 3: Write minimal implementation**

`llm_evaluation/langsmith/__init__.py`: 빈 파일.

`llm_evaluation/langsmith/evaluators.py`:
```python
from __future__ import annotations

import re
from datetime import date

from pydantic import TypeAdapter, ValidationError

from agents.todo_creation.schemas import PlannerResult

# 카나·한자·키릴 (한글/라틴/숫자/기호는 허용)
_FOREIGN = re.compile(r"[぀-ヿ一-鿿Ѐ-ӿ]")
_PLANNER_ADAPTER = TypeAdapter(PlannerResult)


def _r(key: str, score: int | None, comment: str = "") -> dict:
    return {"key": key, "score": score, "comment": comment}


def structure_valid(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """결과가 PlannerResult 유니온으로 파싱되는가 (TaskCandidate 필드 포함)."""
    try:
        _PLANNER_ADAPTER.validate_python(outputs["result"])
        return _r("structure_valid", 1)
    except ValidationError as err:
        return _r("structure_valid", 0, str(err)[:300])


def routing_correct(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """category가 기대하는 kind로 라우팅됐는가."""
    expected = reference_outputs.get("expected_kind")
    actual = outputs.get("kind")
    return _r("routing_correct", int(actual == expected), f"expected={expected} actual={actual}")


def date_sanity(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """candidates의 모든 due_date가 today 이후인가."""
    if outputs.get("kind") != "candidates":
        return _r("date_sanity", None, "n/a")
    today = date.fromisoformat(inputs["today"])
    items = outputs["result"].get("todos", []) + outputs["result"].get("calendar_events", [])
    bad = [i["due_date"] for i in items if date.fromisoformat(i["due_date"]) < today]
    return _r("date_sanity", int(not bad), f"past_due={bad}")


def korean_only(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """렌더되는 텍스트 필드에 외국어(카나·한자·키릴) 누출이 없는가."""
    res = outputs["result"]
    texts: list[str] = []
    if outputs.get("kind") == "candidates":
        for i in res.get("todos", []) + res.get("calendar_events", []):
            texts.append(i.get("title", ""))
            texts.extend(i.get("tags", []))
    elif outputs.get("kind") == "follow_up":
        texts.append(res.get("question", ""))
    elif outputs.get("kind") == "out_of_scope":
        texts.append(res.get("message", ""))
    leaked = [t for t in texts if _FOREIGN.search(t)]
    return _r("korean_only", int(not leaked), f"leaked={leaked}")


def frontend_contract(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
    """mongle-web 렌더에 필요한 필드를 다 담는가 (계약 수준).

    candidates: todos/calendar_events 리스트 + 각 항목 title/due_date/tags.
    follow_up: question. out_of_scope: message.
    """
    kind = outputs.get("kind")
    res = outputs["result"]
    if kind == "candidates":
        for key in ("todos", "calendar_events"):
            if not isinstance(res.get(key), list):
                return _r("frontend_contract", 0, f"missing list: {key}")
        for i in res["todos"] + res["calendar_events"]:
            if not all(k in i for k in ("title", "due_date", "tags")):
                return _r("frontend_contract", 0, f"task missing fields: {i}")
        return _r("frontend_contract", 1)
    if kind == "follow_up":
        return _r("frontend_contract", int(bool(res.get("question"))))
    if kind == "out_of_scope":
        return _r("frontend_contract", int(bool(res.get("message"))))
    return _r("frontend_contract", 0, f"unknown kind: {kind}")


HEURISTIC_EVALUATORS = [
    structure_valid, routing_correct, date_sanity, korean_only, frontend_contract,
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/llm_evaluation/test_evaluators.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add llm_evaluation/langsmith/__init__.py llm_evaluation/langsmith/evaluators.py \
        tests/llm_evaluation/test_evaluators.py
git commit -m "feat: 휴리스틱 planner 평가자 5종"
```

---

## Task 3: judge 재사용 평가자 (LLM)

**Files:**
- Modify: `llm_evaluation/langsmith/evaluators.py` (팩토리 추가)
- Test: `tests/llm_evaluation/test_judge_evaluators.py`

**Interfaces:**
- Consumes: `judge.judge_sufficiency(*, history, message, today, user_profile_memory) -> tuple[bool, list[str], dict]`.
- Produces: `make_judge_evaluators(judge) -> list` — 비동기 평가자 `plan_justified`, `followup_needed`. 각 `async (outputs, reference_outputs, inputs) -> dict`.

- [ ] **Step 1: Write the failing test**

`tests/llm_evaluation/test_judge_evaluators.py`:
```python
import pytest
from llm_evaluation.langsmith.evaluators import make_judge_evaluators


class _FakeJudge:
    def __init__(self, sufficient, missing):
        self._sufficient, self._missing = sufficient, missing
        self.calls = []

    async def judge_sufficiency(self, *, history, message, today, user_profile_memory=None):
        self.calls.append({"history": history, "message": message})
        return self._sufficient, self._missing, {"goal_tag": "목표"}


def _inputs(turns):
    return {"user_id": "u1", "turns": turns, "today": "2026-07-15", "user_profile_memory": None}


def _by_key(evals, key):
    return next(e for e in evals if e.__name__ == key)


@pytest.mark.anyio
async def test_plan_justified_scores_sufficient():
    judge = _FakeJudge(sufficient=True, missing=[])
    evals = make_judge_evaluators(judge)
    out = {"kind": "candidates", "result": {"kind": "candidates"}}
    res = await _by_key(evals, "plan_justified")(out, {}, _inputs(["A", "B"]))
    assert res["score"] == 1
    # 마지막 턴이 message, 앞 턴이 history
    assert judge.calls[-1]["message"] == "B"


@pytest.mark.anyio
async def test_plan_justified_na_for_followup():
    judge = _FakeJudge(sufficient=True, missing=[])
    evals = make_judge_evaluators(judge)
    out = {"kind": "follow_up", "result": {"kind": "follow_up"}}
    res = await _by_key(evals, "plan_justified")(out, {}, _inputs(["A"]))
    assert res["score"] is None


@pytest.mark.anyio
async def test_followup_needed_when_judge_agrees_insufficient():
    judge = _FakeJudge(sufficient=False, missing=["deadline"])
    evals = make_judge_evaluators(judge)
    out = {"kind": "follow_up", "result": {"kind": "follow_up"}}
    res = await _by_key(evals, "followup_needed")(out, {}, _inputs(["시험 공부"]))
    assert res["score"] == 1


@pytest.mark.anyio
async def test_followup_inappropriate_when_judge_says_sufficient():
    judge = _FakeJudge(sufficient=True, missing=[])
    evals = make_judge_evaluators(judge)
    out = {"kind": "follow_up", "result": {"kind": "follow_up"}}
    res = await _by_key(evals, "followup_needed")(out, {}, _inputs(["11월 3일 정보처리기사"]))
    assert res["score"] == 0
```

> 참고: 리포에 `anyio` 픽스처 규약이 있으면 따르고, 없으면 `conftest.py`에 `@pytest.fixture\ndef anyio_backend(): return "asyncio"` 추가. (기존 async 테스트가 `tests/`에 있으니 규약 재사용.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/llm_evaluation/test_judge_evaluators.py -v`
Expected: FAIL (ImportError: make_judge_evaluators)

- [ ] **Step 3: Write minimal implementation**

`llm_evaluation/langsmith/evaluators.py` 하단에 추가:
```python
from datetime import date as _date


def _history_from_turns(prev_turns: list[str]) -> list[dict]:
    # ponytail: assistant 응답을 저장하지 않으므로 이전 턴을 user 발화로만 재구성.
    #           judge_sufficiency는 사용자 발화 누적으로 충분성을 판단하므로 충분.
    return [{"role": "user", "content": t} for t in prev_turns]


def make_judge_evaluators(judge) -> list:
    """기존 judge_sufficiency 를 재사용하는 LLM 평가자 2종을 만든다.

    plan_justified: 플랜을 낸 example에서 judge가 '정보 충분'이라고 보면 1
                    (충분치 않은데 플랜을 냈으면 0 — 성급한 플랜).
    followup_needed: 꼬리질문을 던진 example에서 judge도 '정보 부족'이라 보면 1
                    (충분한데 되물었으면 0 — 불필요한 꼬리질문).
    """

    async def plan_justified(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
        if outputs.get("kind") != "candidates":
            return _r("plan_justified", None, "n/a (non-plan)")
        turns = inputs["turns"]
        sufficient, missing, _goal = await judge.judge_sufficiency(
            history=_history_from_turns(turns[:-1]),
            message=turns[-1],
            today=_date.fromisoformat(inputs["today"]),
            user_profile_memory=inputs.get("user_profile_memory"),
        )
        return _r("plan_justified", int(sufficient), f"judge_missing={missing}")

    async def followup_needed(outputs: dict, reference_outputs: dict, inputs: dict) -> dict:
        if outputs.get("kind") != "follow_up":
            return _r("followup_needed", None, "n/a (non-followup)")
        turns = inputs["turns"]
        sufficient, missing, _goal = await judge.judge_sufficiency(
            history=_history_from_turns(turns[:-1]),
            message=turns[-1],
            today=_date.fromisoformat(inputs["today"]),
            user_profile_memory=inputs.get("user_profile_memory"),
        )
        return _r("followup_needed", int(not sufficient), f"judge_missing={missing}")

    return [plan_justified, followup_needed]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/llm_evaluation/test_judge_evaluators.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add llm_evaluation/langsmith/evaluators.py tests/llm_evaluation/test_judge_evaluators.py
git commit -m "feat: judge_sufficiency 재사용 평가자 (plan_justified, followup_needed)"
```

---

## Task 4: 데이터셋 (시드 + 업로더)

**Files:**
- Create: `llm_evaluation/langsmith/datasets/planner_cases.jsonl`
- Create: `llm_evaluation/langsmith/dataset.py`
- Test: `tests/llm_evaluation/test_dataset.py`

**Interfaces:**
- Produces: `load_cases(path: str | Path | None = None) -> list[dict]` (각 dict: `inputs`, `reference_outputs`, `metadata`), `ensure_dataset(client, name: str, cases_path: str | Path | None = None) -> str` (dataset id 반환, 멱등).
- case 스키마: `{"inputs": {"user_id","turns":[...],"today","user_profile_memory"}, "reference_outputs": {"category","expected_kind"}, "metadata": {"note"}}`.

- [ ] **Step 1: 시드 케이스 작성**

`llm_evaluation/langsmith/datasets/planner_cases.jsonl` (한 줄 = 한 example. 사용자는 여기 append하면 증분됨):
```json
{"inputs": {"user_id": "eval-1", "turns": ["다음 주 토요일까지 정보처리기사 실기 준비하고 싶어"], "today": "2026-07-15", "user_profile_memory": null}, "reference_outputs": {"category": "시험", "expected_kind": "candidates"}, "metadata": {"note": "명확한 시험+마감 → 바로 플랜"}}
{"inputs": {"user_id": "eval-2", "turns": ["운동 좀 해야겠어"], "today": "2026-07-15", "user_profile_memory": null}, "reference_outputs": {"category": "follow_up", "expected_kind": "follow_up"}, "metadata": {"note": "목표 모호 → 꼬리질문 기대"}}
{"inputs": {"user_id": "eval-3", "turns": ["오늘 날씨 어때?"], "today": "2026-07-15", "user_profile_memory": null}, "reference_outputs": {"category": "out_of_scope", "expected_kind": "out_of_scope"}, "metadata": {"note": "플래너 범위 밖"}}
{"inputs": {"user_id": "eval-4", "turns": ["운동 좀 해야겠어", "3주 동안 주 3회 헬스"], "today": "2026-07-15", "user_profile_memory": null}, "reference_outputs": {"category": "일상", "expected_kind": "candidates"}, "metadata": {"note": "멀티턴: 모호→꼬리질문→답변→플랜"}}
{"inputs": {"user_id": "eval-5", "turns": ["11월 20일 토익 시험 준비"], "today": "2026-07-15", "user_profile_memory": null}, "reference_outputs": {"category": "시험", "expected_kind": "candidates"}, "metadata": {"note": "회귀: 일상→시험 붕괴/외국어 누출 감시"}}
```

- [ ] **Step 2: Write the failing test**

`tests/llm_evaluation/test_dataset.py`:
```python
from pathlib import Path
from llm_evaluation.langsmith.dataset import load_cases

_SEED = Path("llm_evaluation/langsmith/datasets/planner_cases.jsonl")


def test_load_cases_parses_seed():
    cases = load_cases(_SEED)
    assert len(cases) >= 5
    first = cases[0]
    assert set(first) >= {"inputs", "reference_outputs"}
    assert "turns" in first["inputs"]
    assert first["reference_outputs"]["expected_kind"] in {"candidates", "follow_up", "out_of_scope"}


def test_multiturn_case_present():
    cases = load_cases(_SEED)
    assert any(len(c["inputs"]["turns"]) >= 2 for c in cases)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/llm_evaluation/test_dataset.py -v`
Expected: FAIL (ModuleNotFoundError: dataset)

- [ ] **Step 4: Write minimal implementation**

`llm_evaluation/langsmith/dataset.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_SEED = Path(__file__).parent / "datasets" / "planner_cases.jsonl"


def load_cases(path: str | Path | None = None) -> list[dict]:
    """jsonl 시드를 파싱해 example dict 리스트로 반환."""
    p = Path(path) if path else _DEFAULT_SEED
    cases: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def ensure_dataset(client, name: str, cases_path: str | Path | None = None) -> str:
    """LangSmith 데이터셋을 멱등 생성하고 example을 채운다. dataset id 반환.

    이미 있으면 재사용하고, 아직 없는 (inputs) 조합만 추가한다.
    """
    cases = load_cases(cases_path)
    if client.has_dataset(dataset_name=name):
        ds = client.read_dataset(dataset_name=name)
    else:
        ds = client.create_dataset(dataset_name=name)

    existing = {
        json.dumps(ex.inputs, sort_keys=True, ensure_ascii=False)
        for ex in client.list_examples(dataset_id=ds.id)
    }
    to_add = [
        c for c in cases
        if json.dumps(c["inputs"], sort_keys=True, ensure_ascii=False) not in existing
    ]
    if to_add:
        client.create_examples(
            dataset_id=ds.id,
            inputs=[c["inputs"] for c in to_add],
            outputs=[c.get("reference_outputs") for c in to_add],
            metadata=[c.get("metadata") for c in to_add],
        )
    return str(ds.id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/llm_evaluation/test_dataset.py -v`
Expected: PASS (2 passed) — `load_cases`는 네트워크 불필요. `ensure_dataset`은 스모크(Task 5)에서 검증.

- [ ] **Step 6: Commit**

```bash
git add llm_evaluation/langsmith/dataset.py llm_evaluation/langsmith/datasets/planner_cases.jsonl \
        tests/llm_evaluation/test_dataset.py
git commit -m "feat: planner 평가 데이터셋 시드 + 멱등 업로더"
```

---

## Task 5: 실행 스크립트 (target + aevaluate)

**Files:**
- Create: `llm_evaluation/langsmith/run_eval.py`

**Interfaces:**
- Consumes: `run()`, `AppConfig.from_env()`, `build_todo_planner_ports()`, `HEURISTIC_EVALUATORS`, `make_judge_evaluators()`, `ensure_dataset()`.
- Produces: `python -m llm_evaluation.langsmith.run_eval` 실행 → 실험 URL 출력.

- [ ] **Step 1: Write the script**

`llm_evaluation/langsmith/run_eval.py`:
```python
"""라이브 RunPod planner 를 데이터셋으로 평가하고 LangSmith 실험으로 올린다.

전제:
  - .env 에 LANGSMITH_TRACING/LANGSMITH_API_KEY + RunPod(RUNPOD_*) 키가 있어야 함.
실행:
  uv run python -m llm_evaluation.langsmith.run_eval
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()

from langsmith import Client
from langsmith.evaluation import aevaluate

from agents._shared.observability import init_langsmith
from agents.todo_creation.planner.pipeline import run
from agents.todo_creation.schemas import PlannerInput
from api.config import AppConfig
from api.deps import build_todo_planner_ports
from llm_evaluation.langsmith.dataset import ensure_dataset
from llm_evaluation.langsmith.evaluators import (
    HEURISTIC_EVALUATORS,
    make_judge_evaluators,
)

_DATASET = "mongle-planner-eval"

_CFG = AppConfig.from_env()
_PORTS = build_todo_planner_ports(_CFG)


async def _target(inputs: dict) -> dict:
    """멀티턴 turns 를 같은 thread_id 로 재생하고 마지막 결과를 반환."""
    today = date.fromisoformat(inputs["today"])
    now = datetime.combine(today, datetime.min.time())
    thread_id: str | None = None
    result = None
    for msg in inputs["turns"]:
        pi = PlannerInput(
            user_id=inputs["user_id"],
            message=msg,
            today=today,
            thread_id=thread_id,
            user_profile_memory=inputs.get("user_profile_memory"),
        )
        result = await run(pi, ports=_PORTS, now=now)
        thread_id = result.thread_id
    return {"kind": result.kind, "result": result.model_dump(mode="json")}


async def main() -> None:
    if not init_langsmith():
        raise SystemExit("LANGSMITH_TRACING/LANGSMITH_API_KEY 가 .env 에 필요합니다.")
    client = Client()
    ensure_dataset(client, _DATASET)
    judge = _PORTS.classifier or _PORTS.llm
    evaluators = [*HEURISTIC_EVALUATORS, *make_judge_evaluators(judge)]
    results = await aevaluate(
        _target,
        data=_DATASET,
        evaluators=evaluators,
        experiment_prefix="planner",
        max_concurrency=2,  # ponytail: RunPod 동시성 보수적. 처리량 필요하면 올릴 것.
    )
    print(f"실험 완료: {results}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 스모크 실행 (키 필요 — 수동)**

전제: `.env`에 `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, RunPod(`RUNPOD_*`) 키.
Run: `uv run python -m llm_evaluation.langsmith.run_eval`
Expected: 콘솔에 실험 URL/요약 출력. https://smith.langchain.com 에서
- 트레이스 트리(`validate→planner→plan_generator/follow_up/out_of_scope` + `runpod_llm` LLM 스팬) 확인 (목표 1·2)
- 각 example의 평가자 점수(structure_valid/routing_correct/date_sanity/korean_only/frontend_contract/plan_justified/followup_needed) 확인 (목표 1·3 + 꼬리질문·멀티턴)

> RunPod 키 만료 이력 있음 — 401/타임아웃이면 키부터 갱신. LangSmith만 검증하려면
> `_PORTS`를 로컬/모의 LLM으로 바꿔 스모크 가능(선택).

- [ ] **Step 3: Commit**

```bash
git add llm_evaluation/langsmith/run_eval.py
git commit -m "feat: LangSmith planner 평가 실행 스크립트 (aevaluate + 멀티턴 target)"
```

---

## Task 6: 이전/이후 비교 리포트 (자동)

**Files:**
- Create: `llm_evaluation/langsmith/compare.py`
- Test: `tests/llm_evaluation/test_compare.py`

**목적:** LangSmith 내장 비교 뷰(수동 스크린샷)와 별개로, 두 실험의 평가자별 평균
점수를 SDK로 뽑아 **self-contained HTML 비교표**(before→after delta, 회귀는 빨강)로
남긴다. 재현·공유 가능한 산출물. (LangSmith는 스크린샷을 API로 안 주므로 화면 캡처는
수동, 이 리포트는 코드 생성.)

**Interfaces:**
- Consumes: `Client.read_project(project_name=...).feedback_stats` (evaluator_key →
  `{"n": int, "avg": float}`).
- Produces: `experiment_scores(client, experiment: str) -> dict[str, float]`
  (evaluator_key → avg), `render_comparison_html(before: dict[str, float], after: dict[str, float], *, before_name: str, after_name: str) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/llm_evaluation/test_compare.py`:
```python
from llm_evaluation.langsmith.compare import render_comparison_html


def test_render_shows_delta_and_regression():
    before = {"structure_valid": 1.0, "routing_correct": 0.8, "date_sanity": 1.0}
    after = {"structure_valid": 1.0, "routing_correct": 0.6, "korean_only": 0.9}
    html = render_comparison_html(before, after, before_name="A", after_name="B")
    assert "<table" in html and "</html>" not in html  # 조각이 아니라 self-contained 문서
    assert "routing_correct" in html
    assert "-0.20" in html          # 0.8 → 0.6 회귀 delta 표기
    assert "korean_only" in html    # after 에만 있는 평가자도 행에 포함
    assert "structure_valid" in html


def test_render_handles_missing_keys_as_na():
    html = render_comparison_html({"a": 1.0}, {}, before_name="A", after_name="B")
    assert "n/a" in html  # after 에 없는 지표는 n/a
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/llm_evaluation/test_compare.py -v`
Expected: FAIL (ModuleNotFoundError: compare)

- [ ] **Step 3: Write minimal implementation**

`llm_evaluation/langsmith/compare.py`:
```python
"""두 LangSmith 실험의 평가자 평균을 뽑아 before/after HTML 비교표를 만든다.

실행:
  uv run python -m llm_evaluation.langsmith.compare <before_experiment> <after_experiment> -o compare.html
"""
from __future__ import annotations

import argparse
import html as _html


def experiment_scores(client, experiment: str) -> dict[str, float]:
    """실험(=LangSmith project)의 평가자별 평균 점수를 반환."""
    stats = client.read_project(project_name=experiment).feedback_stats or {}
    return {key: float(v.get("avg", 0.0)) for key, v in stats.items()}


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render_comparison_html(
    before: dict[str, float],
    after: dict[str, float],
    *,
    before_name: str,
    after_name: str,
) -> str:
    """self-contained HTML 문서(인라인 CSS, 라이트/다크 대응) 반환."""
    keys = sorted(set(before) | set(after))
    rows = []
    for k in keys:
        b, a = before.get(k), after.get(k)
        delta = None if (b is None or a is None) else a - b
        color = ""
        if delta is not None and delta < 0:
            color = ' style="color:#d33"'   # 회귀
        elif delta is not None and delta > 0:
            color = ' style="color:#2a2"'   # 개선
        delta_txt = "n/a" if delta is None else f"{delta:+.2f}"
        rows.append(
            f"<tr><td>{_html.escape(k)}</td><td>{_fmt(b)}</td>"
            f"<td>{_fmt(a)}</td><td{color}>{delta_txt}</td></tr>"
        )
    body = "\n".join(rows)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Planner eval: before/after</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #8884; padding: .4rem .8rem; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#111; color:#eee; }} }}
</style></head><body>
<h1>Planner 평가 비교</h1>
<p>{_html.escape(before_name)} → {_html.escape(after_name)}</p>
<table>
<thead><tr><th>evaluator</th><th>{_html.escape(before_name)}</th>
<th>{_html.escape(after_name)}</th><th>Δ</th></tr></thead>
<tbody>
{body}
</tbody></table>
</body></html>"""


def main() -> None:
    from langsmith import Client

    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("-o", "--out", default="compare.html")
    args = ap.parse_args()

    client = Client()
    html_doc = render_comparison_html(
        experiment_scores(client, args.before),
        experiment_scores(client, args.after),
        before_name=args.before,
        after_name=args.after,
    )
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html_doc)
    print(f"작성: {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/llm_evaluation/test_compare.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 스모크 (두 실험 필요 — 수동)**

run_eval을 두 번 돌려 실험 두 개(예: `planner-abc123`, `planner-def456`)를 만든 뒤:
Run: `uv run python -m llm_evaluation.langsmith.compare planner-abc123 planner-def456 -o compare.html`
Expected: `compare.html` 생성. 브라우저로 열어 평가자별 before→after·delta 확인.
(실험 이름은 `aevaluate` 출력 또는 LangSmith 프로젝트 목록에서 확인.)

> 이 HTML은 self-contained라 Artifact로 공유 링크 발행도 가능.

- [ ] **Step 6: Commit**

```bash
git add llm_evaluation/langsmith/compare.py tests/llm_evaluation/test_compare.py
git commit -m "feat: 이전/이후 실험 비교 HTML 리포트"
```

---

## Task 7: 프롬프트·구조 개선 루프 (Phase 2 — 메인 목적, 반복)

**성격:** Task 1–6이 그린이 된 뒤 실행하는 **데이터 주도 반복 프로토콜**. 어떤 프롬프트를
어떻게 고칠지는 baseline 평가 결과가 정한다 — 그래서 고정 편집이 아니라 루프로 규정한다.
수정 1건마다 아래 5스텝을 돈다.

**방법론 정박(`sft_pipeline/docs/idea/sft_citation.md`, 논문 5편 — 현재 git `2d352e9`에만):**
모든 수정은 논문 원칙을 따른다. **LLM-Modulo**: LLM은 "무엇을+상대배치"만, 절대 날짜
산수는 코드(`allocator.py`), 검증은 외부(judge/코드) — 프롬프트에 달력 계산·self-critique를
넣지 않는다. **Clarify-When-Necessary / Curiosity-by-Design / What-Prompts-Don't-Say**:
꼬리질문은 under-specified일 때만, 빠진 최고가치 슬롯을 묻게.

**Files (수정 대상 후보 — 발견에 따라 1곳만 외과적 수정):**
- 프롬프트: `adapters/todo_creation/_prompts.py`
  - `REQUEST_CLASSIFIER_SYSTEM`(라우팅) · `PLANNER_JUDGE_SYSTEM`(충분성) ·
    `FOLLOW_UP_SYSTEM`(꼬리질문) · `PLAN_GENERATOR_SYSTEM`(날짜별 플랜) ·
    `PLAN_VALIDATOR_SYSTEM` · `GOAL_TAG_SYSTEM` · `OUT_OF_SCOPE_REPLY_SYSTEM`
- 구조: `agents/todo_creation/planner/graph.py`(배선) · `planner/nodes/*` ·
  `planner/allocator.py`(날짜 분배) · `planner/goal_rules.py`(plan_kind 규칙)

**Interfaces:** 신규 코드 없음 — Task 5(`run_eval`)·Task 6(`compare`)을 그대로 소비.

- [ ] **Step 1: baseline 실험 확보**

Run: `uv run python -m llm_evaluation.langsmith.run_eval`
결과 실험 이름을 기록(예: `planner-<baseline>`). LangSmith에서 평가자별 평균을 본다.

- [ ] **Step 2: 최저 점수 클러스터 식별**

LangSmith 실험 뷰에서 점수 낮은 (평가자 × 카테고리) 조합을 고른다. 예시 판정(정박 논문):
  - `korean_only` 낮음 → 외국어 누출(회귀). 레버: `PLAN_GENERATOR_SYSTEM`/`FOLLOW_UP_SYSTEM` 언어 지시. (LLM-Modulo soft/style critic + 코드 후처리)
  - event 라우팅 오류(철인삼종이 exam으로) → `REQUEST_CLASSIFIER_SYSTEM` 또는 `goal_rules.normalize_competition_event_goal`. (뉴로-심볼릭 분업 — 규칙은 코드)
  - `plan_justified`=0(정보 부족한데 플랜) → `PLANNER_JUDGE_SYSTEM` 충분성 기준. (**LLM-Modulo** hard critic=외부 judge, self-verification 금지)
  - `followup_needed`=0(불필요/엉뚱한 꼬리질문) → `PLANNER_JUDGE_SYSTEM`/`FOLLOW_UP_SYSTEM`. (**Clarify-When-Necessary**·**Curiosity-by-Design**: under-specified일 때만·최고가치 슬롯)
  - `date_sanity` 낮음 → **프롬프트 아님**. `allocator.py`/코드 매핑 고침(LLM-Modulo: 날짜 산수는 코드 책임).

- [ ] **Step 3: 가설대로 1곳만 수정 (외과적)**

워크드 예시 — `korean_only` 회귀 가정. `_prompts.py`의 `PLAN_GENERATOR_SYSTEM`에
언어 제약 한 줄을 강화(EXAONE 실측 문구 기준, 실제 문구는 baseline 출력 보고 결정):
```python
# adapters/todo_creation/_prompts.py — PLAN_GENERATOR_SYSTEM 내부 규칙 목록에 추가
# 모든 title·tags 는 한국어만. 한자·가나·키릴 문자를 절대 쓰지 말 것.
```
> 실제 수정은 Step 2에서 고른 심볼 1곳에 한정. 두 곳 동시 수정 금지(효과 귀속 불가).

- [ ] **Step 4: 재평가 + before/after 비교**

Run: `uv run python -m llm_evaluation.langsmith.run_eval`
→ 새 실험 이름 기록(예: `planner-<after>`).
Run: `uv run python -m llm_evaluation.langsmith.compare planner-<baseline> planner-<after> -o compare.html`
Expected: `compare.html`에서 고친 평가자의 Δ가 양수(개선). 다른 평가자 회귀 없음 확인.

- [ ] **Step 5: 개선이면 커밋, 회귀면 되돌림**

개선(타깃 Δ>0, 회귀 없음)일 때만:
```bash
git add adapters/todo_creation/_prompts.py
git commit -m "fix(planner): <심볼> <개선 내용> (eval Δ +N, exp planner-<after>)"
```
회귀/무변화면 `git checkout -- adapters/todo_creation/_prompts.py`로 되돌리고 Step 2 재선택.

> 각 반복은 프롬프트/구조 diff + 실험 링크를 커밋 메시지에 남겨 근거를 추적한다.
> 다음 baseline은 방금 커밋한 상태가 된다(누적 개선).

---

## Self-Review 결과

- **Spec 커버리지**: Tracing(Task 1) / 휴리스틱·frontend_contract(Task 2) / judge 재사용·꼬리질문(Task 3) / 멀티턴 데이터셋(Task 4) / 라이브 RunPod target·실험(Task 5) / 이전-이후 비교 리포트(Task 6) / **프롬프트·구조 개선 루프(Task 7, 메인 목적, 논문 5편 정박)** — spec의 세 컴포넌트 모두 태스크 있음. Phase 1(Task 1–6)=피드백 루프 구축, Phase 2(Task 7)=EXAONE 어댑터 프롬프트/구조 개선.
- **Placeholder**: 모든 스텝에 실제 코드/명령/기대출력 있음. TBD 없음.
- **타입 일관성**: 평가자 반환 규약 `{"key","score","comment"}`, target 출력 `{"kind","result"}`, example `inputs/reference_outputs` 규약이 Task 2·3·4·5에서 일치. `judge_sufficiency` 시그니처 = 확정 인터페이스와 일치.
- **알려진 한계(ceiling)**: `validate_plan`(중간 PlanDay/ParsedGoal 필요)은 최종 결과에 미노출이라 미사용 → judge_sufficiency로 대체. 중간 상태를 노출하면 더 정밀한 plan_justified로 업그레이드 가능. `feat/planner-all-openai` 머지 시 `@traceable` wrap 불필요(langchain-native 자동 추적).
