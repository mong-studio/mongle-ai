# 단일턴 `generate` out_of_scope 처리 설계

**작성일:** 2026-06-13
**범위:** `agents/todo_creation/todo/`(단일턴 generate 파이프라인)에 범위 판단(intent)을 도입한다. "배고프다"처럼 일정/TODO로 나눌 수 없는 입력을 `OutOfScopeResult` 로 응답하고, 억지 todo 생성을 막는다. 멀티턴 플래너(`chat`)·`commit` 은 변경하지 않는다.

**관련 문서:**

- 멀티턴 도입 spec: [./2026-05-25-todo-multiturn-design.md](./2026-05-25-todo-multiturn-design.md)
- 피처 사양: [../../features/todo/CLAUDE.md](../../features/todo/CLAUDE.md)
- 공통 AI 규칙: [../../AI_RULES.md](../../AI_RULES.md)
- 기존 out_of_scope 구현(재사용): `agents/todo_creation/planner/nodes/out_of_scope.py`

---

## 0. 배경 / 문제

단일 `POST /v1/todo/generate` 파이프라인은 `validate → task_splitter → date_router` 뿐이고 범위 판단 노드가 없다. 그 결과 "배고프다" 같은 비-목표 입력도 `split_tasks` 로 넘어가 모델이 억지 todo 를 만든다.

검증(2026-06-13, prod RunPod planner 엔드포인트):

| 입력 | `/v1/todo/generate` | `/v1/todo/chat` |
| --- | --- | --- |
| "배고프다" | ❌ `candidates` + 지어낸 todo 3개(밥 먹기·음료 사기·건강식품 확인) | ✅ `out_of_scope` + 안내 메시지 |

범위 판단(`intent: "plan" \| "out_of_scope"`)은 플래너의 `PLANNER_JUDGE_SYSTEM` 에만 존재한다.

## 1. 결정 요약 (Brainstorm Outcomes)

| # | 결정 | 근거 |
| --- | --- | --- |
| D1 | **Approach A — 기존 `split_tasks` 1회 호출에 `intent` 를 합친다** | 단일턴의 핵심 가치는 빠른 1-shot. 별도 판정 노드(Approach B)는 LLM 호출을 2배로 늘려 지연·비용 증가 |
| D2 | split 출력 스키마를 `{"intent": "plan"\|"out_of_scope", "tasks": [...]}` 로 확장 | 플래너에서 검증된 패턴 |
| D3 | **파서 하위호환: `intent` 키 누락 시 `"plan"` 으로 간주** | 모델이 새 필드를 안 내도 기존 동작 유지 → 무회귀 |
| D4 | `OutOfScopeResult` 스키마·`_OUT_OF_SCOPE_MESSAGE` 안내문구를 chat 과 공유 | 응답 형태·문구 일관, 클라이언트의 `kind` 분기 재사용 |
| D5 | 단일턴 응답모델 `Envelope[GenerateResult]` → `Envelope[SingleTurnResult]`(=`GenerateResult \| OutOfScopeResult`, `kind` 디스크리미네이터) | chat 의 `TurnResult` 와 동형. FollowUpResult 는 단일턴에 없으므로 2-멤버 유니온 |
| D6 | 단일턴 `OutOfScopeResult.thread_id = ""` | 단일턴은 thread 없음. `GenerateResult.thread_id` 기본 `""` 와 동일 관례 |
| D7 | quest_generation·planner(chat)·commit 미변경 | 범위 격리 |

**기각: Approach B (split 앞 별도 scope 판정 노드)** — split 프롬프트를 안 건드리는 장점이 있으나 단일턴 LLM 호출이 2배가 되어 1-shot 가치를 훼손. D1 참조.

## 2. 변경 지점

| 파일 | 변경 |
| --- | --- |
| `adapters/todo_creation/_prompts.py` | `TASK_SPLITTER_SYSTEM` 에 intent 규칙 + out_of_scope 예시 추가, 스키마를 `{"intent","tasks"}` 로. out_of_scope 정의는 `PLANNER_JUDGE_SYSTEM` 의 문구("날씨·잡담·단순 지식 질의처럼 목표를 일정/TODO로 나눌 수 없는 경우")와 정합 |
| `adapters/todo_creation/qwen_llm.py` | `parse_task_response` 가 `(intent, tasks)` 를 함께 파싱. `intent` 누락→`"plan"`(D3). out_of_scope 면 `tasks` 빈 배열이 정상. `split_tasks` 반환 형태에 intent 포함 |
| `agents/todo_creation/todo/nodes/task_splitter.py` | out_of_scope 분기. plan 인데 빈 tasks 일 때만 기존 B2 retry/`LLMOutputError` 유지 (out_of_scope 의 빈 tasks 는 에러 아님) |
| `agents/todo_creation/todo/state.py` | `GenerateGraphState` 에 intent/out_of_scope 신호 필드 추가 |
| `agents/todo_creation/todo/pipeline.py` | out_of_scope 면 `date_router` 를 건너뛰고 `OutOfScopeResult` 를 결과로 반환 |
| `agents/todo_creation/schemas.py` | `SingleTurnResult = Annotated[GenerateResult \| OutOfScopeResult, Field(discriminator="kind")]` 추가 |
| `api/todo_creation/router.py` | `/generate` 응답모델·핸들러 반환타입 `Envelope[SingleTurnResult]` 로 |

**재사용**: `OutOfScopeResult`(schemas.py), `_OUT_OF_SCOPE_MESSAGE`(planner/nodes/out_of_scope.py).

## 3. 데이터 흐름

```
generate(TodoInput)
  validate                      # A1/A2/A3 (변경 없음)
  task_splitter
    split_tasks(LLM 1회)        # → {"intent", "tasks"}
    ├─ intent=out_of_scope ──▶ OutOfScopeResult(thread_id="", message=_OUT_OF_SCOPE_MESSAGE) ──▶ END
    └─ intent=plan ──▶ date_router(변경 없음) ──▶ GenerateResult ──▶ END
```

## 4. 오류 처리 / 경계

- plan 인데 tasks 빈 배열: 기존 B2 1회 retry 후에도 비면 `LLMOutputError`(현행 유지).
- out_of_scope 인데 tasks 가 비어있지 않음: tasks 무시하고 out_of_scope 우선(분류가 의도).
- `intent` 값이 `plan`/`out_of_scope` 외: `"plan"` 으로 폴백(D3 정신).
- 비-JSON/스키마 위반: 기존 reinforce 재시도 경로 그대로.

## 5. 테스트

- **단위(파서)**: `intent="out_of_scope"`→out_of_scope 신호 / `intent="plan"`·키 누락→tasks 파싱 / 잘못된 intent→plan 폴백.
- **단위(task_splitter_node)**: out_of_scope→`OutOfScopeResult` 분기 / plan→date_router 진행 / plan+빈 tasks→retry·에러.
- **통합(재배포 후)**:
  - `TST-LLM-OOS-001`: "배고프다" → `result.kind=="out_of_scope"`.
  - `TST-LLM-001`(회귀): "오늘 영어단어 30개 외우고, 토익 복습하고, 산책할 거야" → `todos.length==3`, 모두 오늘.
- 커버리지 80%+ (글로벌 룰).

## 6. 비목표 (Out of scope)

- 멀티턴 플래너·commit·quest 변경.
- 반복 루프(degeneration) 자체의 해결(repetition_penalty 등) — 별도 백로그.
- base vs fine-tune 라우팅 — 본 설계는 모델 무관하게 동작.

## 7. 배포

- 코드 변경은 API 서버(`api/`, `agents/`, `adapters/`)에 한정 → 기존 `deploy-api.yml` 경로로 배포.
- RunPod 워커(`runpod_workers/`)·모델 가중치 변경 없음 → 워커 재배포 불필요.
