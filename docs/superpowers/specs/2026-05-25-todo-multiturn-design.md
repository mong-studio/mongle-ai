# 멀티턴 TODO/플랜 챗봇 설계서

**작성일:** 2026-05-25
**대상:** `agents/todo_creation/multi_turn/`
**관련 문서:** [`docs/features/todo/CLAUDE.md`](../../features/todo/CLAUDE.md), [`architecture.mmd`](../../features/todo/architecture.mmd)

---

## 1. 핵심 결정

| 항목 | 결정 |
|---|---|
| 그래프 패턴 | **Hybrid** — 정보수집=결정론적, 수정 루프=LLM tool-calling |
| 세션 저장 | 커스텀 `SessionStorePort` (in-memory → 추후 MySQL) |
| Commit | 자체 commit 노드 없음, `commit/pipeline.run()` 위임 |
| Edit tools (MVP) | `regenerate_plan(instructions)`, `confirm` |
| 태그 어휘 | 자유 형식 |
| 한국어 검증 | 한글 비율 ≥ 0.3 휴리스틱 |
| C3(≤1500자) 초과 | 재생성 1회 → 실패 시 잘라내기 |

---

## 2. 그래프

```
validate → phase_router
   ├─ gathering → planner_judge → [sufficient?]
   │       ├─ false → follow_up → present(question) → END
   │       └─ true  → plan_generator → tagger → present(plan) → END
   └─ reviewing → edit_agent (tools, recursion_limit=4)
           ├─ regenerate_plan → plan_generator → tagger → present(plan) → END
           └─ confirm → commit_invoke → present(committed) → END
```

- `plan_generator` 는 양쪽 경로에서 진입, `edit_instructions` 유무로 프롬프트 분기
- `session_store.save` 는 `present` 에서, `delete` 는 `commit_invoke` 성공 시에만

---

## 3. 디렉토리

```
agents/todo_creation/multi_turn/
├── pipeline.py · graph.py · state.py · tools.py · session_store.py
└── nodes/
    ├── validate · phase_router · planner_judge · follow_up
    ├── plan_generator · tagger · edit_agent
    └── commit_invoke · present
```

---

## 4. 핵심 타입 (Pydantic)

- **입력:** `MultiTurnInput{user_id, session_id, message≤600, today}`
- **세션:** `SessionState{phase, history(cap 20), parsed_goal, current_plan, ...}`
- **노드 산출:** `PlannerJudgment`, `PlanDraft`, `TaggedPlan`, `AgentDecision`
- **출력:** `TurnResult{kind: question|plan|committed, ...payload}`

상세 필드는 구현 플랜에서.

---

## 5. 포트

```python
class MultiTurnLLMPort(Protocol):
    judge_planner / generate_follow_up / generate_plan / tag_plan / edit_agent_step

class SessionStorePort(Protocol):
    load / save / delete

@dataclass
class MultiTurnPorts:
    llm, session_store, commit_ports
```

`run_turn(input, *, ports, now) -> TurnResult` 가 entry point.

---

## 6. 시나리오 한 줄 요약

| Turn | 사용자 | 그래프 종착지 | session phase |
|---|---|---|---|
| 1 | "3일 후 시험" | follow_up | gathering |
| 2 | "하루 3시간, 60점" | plan_generator → tagger | reviewing |
| 3a | "확정" | commit_invoke (session 삭제) | — |
| 3b | "마지막 날 가볍게" | regenerate_plan → plan_generator → tagger | reviewing |

---

## 7. 에러 & 재시도

- **Validate 실패** (길이/빈/한글비율) → 4xx, LLM 미호출
- **LLM 노드** → `RetryPolicy(max_attempts=2)` (planner_judge, follow_up, plan_generator, tagger)
- **edit_agent** → `RetryPolicy(max_attempts=1)`, `recursion_limit=4`
- **C3 초과** → 노드 내부 1회 재호출, 그래도 초과 시 마침표 기준 잘라내기 (에러 아님)
- **commit 실패** → session 보존 (사용자 재시도 가능)

---

## 8. 테스트

- 단위 테스트: 각 노드 + InMemorySessionStore (single_turn 패턴 그대로)
- 통합 테스트: 시나리오 매트릭스 (Turn 1·2·3a·3b + recursion_limit 도달 + C3 잘라내기 + commit 실패)
- 커버리지 목표 80%+
- `FakeMultiTurnLLM` 큐 기반 (메서드별 응답 큐 + 호출 카운터)

---

## 9. 영향받는 기존 파일

- `protocols.py`, `schemas.py` 에 신규 타입 추가
- `debug.py` `log_start` 시그니처에 `MultiTurnInput` 추가
- `architecture.mmd` MULTI 서브그래프 갱신 (edit_agent, phase_router 반영)
- `docs/features/todo/CLAUDE.md` §7 미결사항 표 갱신
- `CHANGELOG.md`

---

## 10. 범위 밖 (Deferred)

- MySQLSessionStore (Port 인터페이스만 본 PR 확정)
- Streamlit 통합 (후속 PR)
- session TTL 정책
- 세분화 edit tools (modify_day, remove_task 등)
