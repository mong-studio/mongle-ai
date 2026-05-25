# LangGraph 패턴 단순화 — 후속 후보 (③·④)

**작성일:** 2026-05-25
**전제:** 2026-05-25 세션에서 `character_creation` 파이프라인에 **Command 패턴**을 도입해 다음을 완료함:

- `state.Route` / `state.route` 제거 → `validate_node` 가 `Command(goto=[...])` 로 fan-out
- `image_generator` / `generated_upload` / `builder` 가 `Command(goto="success" | "cleanup_source_image")` 반환
- `router.py` (`decide`, `ok_or_cleanup`) 삭제
- `graph.py` 에서 `add_conditional_edges` 4개 제거, `add_node(..., destinations=(...))` 로 가능한 타깃 선언
- 전체 테스트 168 passed, character_creation 자체 64 passed, ruff green

본 스펙은 **그 다음 두 후보**의 결정 근거·위험·검증 전략을 보존한다.

**관련 문서:**

- 직전 작업 영향 받은 코드: `agents/character_creation/{graph.py,state.py,nodes/}`
- 영향 받은 테스트: `tests/agents/character_creation/test_{node_validate,state,image_generator,node_generated_upload,builder,graph}.py`
- 기존 분기 스펙: [./2026-05-24-todo-singleton-commit-design.md](./2026-05-24-todo-singleton-commit-design.md) — generate / commit 두 그래프 분리 결정 (D1)

---

## 0. 결정 요약 (이번 스펙 범위)

| #   | 결정                                                                                     | 근거                                                                  |
| --- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| F1  | 후보 ③·④ 는 **이번 세션에서 진행하지 않음**.                                             | ③ 은 fan-in 타이밍 검증 필요, ④ 는 인프라(checkpointer) 결정 필요.    |
| F2  | ③ 우선순위 = **중**. 인지 부하 1건, 런타임 부담 1회 dummy invoke. 위험은 LangGraph 0.2 의 fan-in semantics 가정. |
| F3  | ④ 우선순위 = **중장기**. 구조 단순화 효과는 가장 크지만 checkpointer 영속화·클라이언트 프로토콜 변경이 결합됨. |
| F4  | **Annotated state (reducers) 도입 안 함**. 현재 모든 병렬 분기가 disjoint 키만 작성 → reducer 수요 없음. 향후 같은 키 동시 쓰기 발생 시 재검토. |

---

## 1. 후보 ③ — `vlm_analyzer` 의 "None 패스스루" 핵 제거

### 1.1 현 상태 (refactor 후 코드 기준)

`agents/character_creation/nodes/vlm_analyzer.py:12-13`:

```python
async def vlm_analyzer_node(state, config):
    if state["input"].source_image is None:
        return {"vlm_result": None}      # ← 핵: fan-in 채널 만족 목적의 dummy invoke
    ...
```

text_only 경로는 `validate_node` 가 `Command(goto=["llm_persona", "vlm_analyzer"])` 로 fan-out 한다 (`agents/character_creation/nodes/validate.py:35-43`). vlm_analyzer 는 즉시 None 을 반환해 단순히 image_generator 의 두 incoming edge 중 하나를 fire 시키는 역할만 한다.

이유: graph.py 에 `add_edge("llm_persona", "image_generator")` 와 `add_edge("vlm_analyzer", "image_generator")` 가 둘 다 있어, image_generator 가 두 predecessor 의 입력을 기다린다고 가정되어 있다.

### 1.2 제안

text_only 경로의 Command 타깃을 `["llm_persona"]` 만으로 축소:

```python
# nodes/validate.py
targets = (
    ["llm_persona", "source_upload"] if state["input"].source_image is not None
    else ["llm_persona"]
)
```

그리고 vlm_analyzer 에서 None 분기 제거:

```python
# nodes/vlm_analyzer.py
async def vlm_analyzer_node(state, config):
    ports = config["configurable"]["ports"]
    for _ in range(MAX_ATTEMPTS):
        try:
            return {"vlm_result": await ports.vlm.extract_appearance(state["input"].source_image)}
        except VLMFailedError:
            continue
    return {"vlm_result": None}     # VLM 실패 시 degrade 는 유지
```

image_generator 는 이미 `vlm_result=None` 일 때 `fallback_persona` 로 동작 (`nodes/image_generator.py:27`) — 다운스트림 변경 불필요.

### 1.3 위험 — LangGraph 0.2 fan-in semantics

**핵심 미해소 질문:** image_generator 의 두 incoming edge (llm_persona, vlm_analyzer) 가 서로 다른 superstep 에서 fire 될 때 image_generator 가 1회만 실행되는가, 아니면 매 superstep 마다 실행되는가?

- image_and_text 경로:
  - SS1: validate
  - SS2: [llm_persona, source_upload] 병렬
  - SS3: vlm_analyzer (source_upload 의 결과 대기). 동시에 image_generator 가 llm_persona 입력만 가지고 fire 될 가능성?
  - SS4: image_generator 가 vlm_analyzer 입력으로 다시 fire?

만약 두 번 실행된다면 `image_generator_node` 안의 `ports.repository.increment(user_id)` 가 두 번 호출되어 카운터가 이중 증가한다 (`nodes/image_generator.py:18`). 현재 통합 테스트 `tests/agents/character_creation/test_graph.py:63-71` 는 `ports.vlm.calls == 1` 은 검증하지만 `ports.repository.increments == 1` 은 검증하지 않는다.

**검증 단계** (③ 진행 시 필수):

1. 회귀 테스트 추가 — `test_graph_image_path_increments_counter_once` 를 먼저 작성하고 현재 코드에서 통과하는지 확인 (= 현재도 1회 실행됨이 보장되는지)
2. 통과한다면 ③ 적용 후 재검증
3. 실패한다면 → 이미 잠재 버그가 있음 → 별도 이슈로 분리, ③ 는 보류

### 1.4 예상 변경 범위

- `nodes/validate.py` (3줄)
- `nodes/vlm_analyzer.py` (4줄)
- `tests/agents/character_creation/test_node_validate.py` — text_only assertion 변경
- `tests/agents/character_creation/test_graph.py` — 회귀 테스트 1건 추가
- `tests/agents/character_creation/test_vlm_analyzer.py` — `test_vlm_analyzer_returns_none_without_calling_vlm_when_no_source_image` 삭제 (해당 경로 자체가 없어짐)

### 1.5 결정 기준

- ✅ 진행: 1.3 의 회귀 테스트가 통과하고 LangGraph 0.2 fan-in 동작이 명확히 1회로 보장됨을 확인했을 때
- ❌ 보류: counter increment 관련 잠재 이상이 발견되면 그 자체를 별도 이슈로 우선 처리

---

## 2. 후보 ④ — `generate` + `commit` 그래프를 `interrupt()` 로 통합

### 2.1 현 상태

[2026-05-24 스펙 D1](./2026-05-24-todo-singleton-commit-design.md) — **"두 개의 컴파일된 LangGraph (generate_graph, commit_graph). interrupt/checkpointer 없음."**

근거: "클라이언트가 후보 상태 보유 (버튼 확정·수정 후 재전송)."

부수 결정:

- **D4**: `CommitInput.idempotency_key` 필수 — 확정 버튼 중복 클릭·재시도 안전 (`agents/todo_creation/commit/nodes/save_dispatcher.py:15`)
- **D5**: commit 단계에서 `due_date` 기준 재분류 — 클라가 수정해 보낸 payload 대응 (`agents/todo_creation/commit/nodes/validate.py:14-25`)

즉 현재 아키텍처는 **클라가 단기 상태 저장소** 역할을 하고 있다.

### 2.2 제안

단일 그래프 + `interrupt()`:

```
START → validate → task_splitter → date_router → interrupt(human_review)
                                                  ↓ Command(resume=edited_payload)
                                              re_validate → save_dispatcher → quest_gate → quest_dispatch → END
```

서버측이 checkpointer 로 상태 보유. 클라는 `thread_id` 만 관리하면 됨.

### 2.3 인프라 비용

| 항목 | 영향 |
|------|------|
| Checkpointer 백엔드 | Postgres / Redis / SQLite 결정 필요. 로컬 dev 와 prod 양쪽. |
| `thread_id` 라이프사이클 | 발급·만료 정책. 현재 idempotency_key 가 차지하던 역할 대체 가능성 |
| 클라이언트 프로토콜 | "generate 호출 → 응답 받음 → commit 호출" 2RTT 모델에서 "stream + resume" 모델로 전환 |
| 멀티턴 (스펙 외) | 멀티턴 도입 시 이미 streaming/checkpointer 가 필요할 수 있어 함께 결정 가능 |
| 관찰성 | trace 가 한 thread 내에서 연결됨 — 디버깅·로깅이 단순해지는 이점 |

### 2.4 단순화 효과

| 사라지는 것 |
|------|
| `agents/todo_creation/single_turn/pipeline.py` + `commit/pipeline.py` → 단일 `pipeline.py` |
| `single_turn/state.py` + `commit/state.py` → 단일 `state.py` (`re_routed_*` 중복 제거) |
| `single_turn/protocols.py::LLMPort` + `commit/CommitPorts` → 단일 Ports |
| `CommitInput.idempotency_key` (선택) — `thread_id` 가 동일 역할 |
| `commit/nodes/validate.py` 의 재분류 로직 — 단일 그래프 내부에서 상태 보유 |

### 2.5 멱등성·재시도 비교

| 시나리오 | 현재 (2그래프) | 제안 (interrupt) |
|----------|---------------|------------------|
| 사용자 확정 버튼 더블 클릭 | `idempotency_key` 매칭 → 기존 결과 반환 | `Command(resume=...)` 두 번 — checkpointer 가 "이미 done" 확인 |
| 사용자 수정 후 재전송 | 새 `commit_graph` 호출, 새 payload | 동일 thread 에 다른 `resume` 페이로드 — 더 자연스러움 |
| 네트워크 실패 후 재시도 | `idempotency_key` 같음 → 안전 | thread 상태 그대로 — 재시도 가능 |

### 2.6 결정 기준

- ✅ 진행: 멀티턴 도입과 묶어서 checkpointer 인프라를 어차피 결정해야 할 때
- ❌ 보류: 현재 D1 의 "클라가 상태 보유" 가 비용 대비 잘 작동하고 있고, 다른 우선순위 작업이 있을 때

### 2.7 선행 작업

본 후보 진행 전 결정해야 할 것:

1. **Checkpointer 선택** — `langgraph.checkpoint.{postgres,redis,sqlite}` 중 어느 것. 운영·테스트 환경.
2. **thread_id 발급 주체** — 클라 / 서버 / API 게이트웨이?
3. **만료 정책** — 사용자가 review 화면을 떠난 후 thread 가 언제 청소되는가?
4. **멀티턴 영향 분석** — 멀티턴 스펙이 어차피 checkpointer 를 요구한다면 함께 진행하는 것이 합리적.

---

## 3. 진행 결정 트리

```
A. ③ 또는 ④ 둘 다 지금 필요한가?
   ├─ No  → 본 스펙을 "참조용"으로만 보존. 향후 우선순위 변동 시 재방문.
   └─ Yes → B 로
B. checkpointer 인프라 결정이 이미 잡혀있나?
   ├─ Yes → ④ 먼저 진행 (큰 단순화 효과 + 인프라가 이미 준비됨)
   └─ No  → C 로
C. ③ 의 fan-in 회귀 테스트가 통과하는가?
   ├─ Yes → ③ 진행 (낮은 위험·낮은 효과지만 인지 부하 1건 해소)
   └─ No  → counter increment 잠재 이상 조사부터.
```

---

## 4. 이번 세션 산출물 (참조)

본 스펙 작성 시점의 코드 상태:

- 변경된 파일 (8개): `state.py`, `graph.py`, `debug.py`, `nodes/{validate,image_generator,generated_upload,builder}.py`, `tests/agents/character_creation/test_{node_validate,state,image_generator,node_generated_upload,builder}.py`
- 삭제된 파일 (2개): `agents/character_creation/router.py`, `tests/agents/character_creation/test_router.py`
- 테스트 결과: 168 passed (전체), 64 passed (character_creation 자체)
- Lint: ruff green

git 커밋은 본 세션 종료 후 별도 단계에서 처리.
