# LangSmith로 RunPod planner 관찰 + 평가

- 날짜: 2026-07-15
- 브랜치: `feat/langsmith-planner-observability`
- 관련: `agents/todo_creation/planner/`, `adapters/todo_creation/runpod_llm.py`, `agents/_shared/observability/`

## 배경 / 문제

RunPod serverless에 떠 있는 planner(**EXAONE-3.5 base + planner LoRA 어댑터**)의
출력을 확인하고, **그 결과를 근거로 프롬프트와 그래프 구조를 고쳐 개선하는 것**이
메인 목적이다. 초기에 언급된 세 가지 확인 항목:

1. 플랜이 구조화되어 잘 출력되는가
2. LangGraph·LangChain을 모두 써서 최적화되어 있는가
3. frontend에서 어떤 질문에서든 원하는 답이 정확하게 나오는가

**중요 — 베이스는 EXAONE, Qwen 아님.** 어댑터 클래스 이름 `QwenLLM`/`RunPodQwenLLM`은
레거시 명칭이고 실제 서빙은 EXAONE-3.5-7.8B에 planner LoRA를 물린 것이다
(source of truth: `runpod_workers/setup_endpoints.py`, `deploy-workers.yml`;
`deployment.md`·Dockerfile 주석의 "Qwen"은 stale). 프롬프트도 EXAONE 어댑터 기준으로
고친다.

현재 상태(코드 확인 결과):

- planner는 이미 RunPod serverless에 배포됨. LangGraph `StateGraph`로 구현
  (`validate → planner → {plan_generator | follow_up | out_of_scope}`).
- `langgraph`, `langchain-core`, `langchain-openai`가 의존성. LangGraph·LangChain은
  **이미 구조적으로 사용 중**. 커스텀 콜백 트레이서도 있음(`observability/trace_base.py`,
  `BaseCallbackHandler` 기반).
- **LangSmith는 어디에도 연동 안 됨**(코드/의존성 0건).
- RunPod LLM 호출은 langchain ChatModel이 아니라 커스텀 `QwenLLM.complete_raw()`.
  → LangGraph 노드는 자동 추적되지만 **LLM 호출은 자동 추적 안 됨**.

즉 실제 과제는 "배포"가 아니라 두 단계다:
- **Phase 1 (수단)**: 관찰(tracing) + 평가(evaluation) 계층을 LangSmith로 붙여
  약점을 드러낸다.
- **Phase 2 (목적)**: 드러난 약점을 근거로 `_prompts.py` 프롬프트와 그래프 구조를
  고치고, before/after 비교로 개선을 확인한다.

## 목표 / 비목표

목표

- 라이브 planner 실행이 LangSmith 트레이스 트리로 보인다(그래프 노드 + LLM 호출).
- frontend형 질문 유형별 데이터셋으로 구조 유효성·정확도를 정량 채점한다.
- **평가를 피드백 루프로 삼아 EXAONE 어댑터 기준 프롬프트·구조를 개선하고,
  before/after 실험 비교로 각 수정의 효과를 수치로 확인한다.**
- 키 없으면 no-op — 프로덕션 경로를 절대 깨지 않는다.

비목표

- 커스텀 관찰 대시보드 제작(LangSmith가 UI).
- 새 judge 모델 도입(기존 `judge_sufficiency` 재사용).
- `QwenLLM`을 langchain ChatModel로 전면 재작성. 경계 하나만 wrap.
  (천장: 완전한 langchain-native 토큰 집계가 필요하면
  `QwenLLM → ChatOpenAI(base_url=vllm)` 마이그레이션이 업그레이드 경로.
  `feat/planner-all-openai` 브랜치가 이 방향. 머지되면 wrap 불필요해짐.)

## Component 1 — Tracing

| 요소 | 내용 |
| --- | --- |
| `agents/_shared/observability/langsmith.py` | `init_langsmith()` — 멱등. `LANGSMITH_TRACING`이 truthy이고 `LANGSMITH_API_KEY`가 있을 때만 활성. 없으면 no-op. API 시작(`api/main.py`)·eval 스크립트에서 호출 |
| `.env` | `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=lsv2_pt_...`, `LANGSMITH_PROJECT=mongle-planner`, `LANGSMITH_ENDPOINT=https://api.smith.langchain.com` |
| LLM 경계 wrap | `QwenLLM.complete_raw`(또는 RunPod 서브클래스)에 `@traceable(run_type="llm", name="runpod:{label}")`. messages·guided_json·출력·라벨·지연 캡처. **에러 흐름(LLMFailedError 재시도) 불변** |
| run 메타데이터 | 기존 contextvars(`user_id_var`/`session_id_var`/`pipeline_id_var`)를 LangSmith run 태그/메타로 전달 → user/thread별 필터 |

결과: 트레이스 트리에
`validate → planner → plan_generator/follow_up/out_of_scope`(LangGraph=목표2) +
각 노드 하위에 `runpod:plan` 등 LLM 스팬(구조화 출력=목표1)이 보인다.

`langsmith` 의존성을 `requirements-api.txt`/`pyproject.toml`에 추가.

## Component 2 — Evaluation

위치: `llm_evaluation/langsmith/` (신규)

- **`dataset.py`** — LangSmith 데이터셋 `mongle-planner-eval` 생성/업로드. 멱등
  (있으면 재사용, 신규 example만 추가).
  - 시드: `tests/` 픽스처 + `scripts/live_planner_smoke.py` 케이스 +
    알려진 회귀(슬롯 환각, 일상→시험 붕괴, cadence 주1회 뭉갬, 외국어 누출, event-day).
  - example 구조: `inputs` = PlannerInput 필드(`user_id`, `message`, `today`,
    optional `user_profile_memory`), `metadata.category` ∈ {일상, 시험, follow_up,
    out_of_scope}, optional `outputs`(reference).
  - **멀티턴 example**: `inputs.turns` = 메시지 배열
    (예: `["시험 준비 도와줘", "다음 주 토요일 정보처리기사"]`). 단일턴은 원소 1개.
    eval target이 `thread_id`를 공유하며 순차 재생 → "부족 → 꼬리질문 → 답변 →
    충분 → 구조화 플랜" 전체 흐름을 한 example로 검증. `metadata.expected_final` ∈
    {follow_up, plan, out_of_scope}로 마지막 턴 기대 결과 표기.
  - **사용자 추가분**: `llm_evaluation/langsmith/datasets/planner_cases.jsonl`에 append.
    `dataset.py`가 이 파일도 읽어 업로드(증분 가능).
- **`evaluators.py`**
  - 휴리스틱(코드, LLM 없음·빠름·결정적):
    - `structure_valid` — 출력이 기대 result 타입으로 Pydantic 파싱되는가 +
      plan task 필수 필드 + `goal_rules` 충족.
    - `routing_correct` — category에 맞는 노드로 라우팅됐는가
      (일상→plan_generator, 애매→follow_up, 무관→out_of_scope).
    - `date_sanity` — 마감일이 과거/`today` 이전 아님, +N일 산술 정상.
    - `korean_only` — 필요한 필드에 외국어 누출 없음(회귀 가드).
    - `frontend_contract` — 최종 PlannerResult가 mongle-web이 렌더에 쓰는 API
      envelope 필드를 다 담는가(계약 수준). 실제 브라우저 렌더링은 비목표 —
      필드 충족만 확인. 정확한 필드는 `docs/api/todo-chat-api.md` +
      `api/todo_creation` 응답 모델에서 핀.
  - LLM-as-judge(기존 judge 재사용, 새 모델 없음):
    - `plan_coherence` — 리포 `judge_sufficiency`로 플랜 의미 정확도 채점.
    - `followup_appropriate` — 정보 부족 시 던진 꼬리질문이 *적절한지*
      (누락 슬롯을 묻는지, 엉뚱한 질문 아닌지). `routing_correct`가 "follow_up으로
      갔는가"만 본다면 이건 질문 내용의 질을 본다.
- **`run_eval.py`** — `evaluate(target, data="mongle-planner-eval",
  evaluators=[...])`. `target`은 `agents.todo_creation.planner.pipeline.run()` 래핑
  → **라이브 RunPod 호출**. 멀티턴 example은 `inputs.turns`를 동일 `thread_id`로
  순차 재생하고 **마지막 턴 결과**를 채점 대상으로 반환. 실험 URL 출력.
  예제별 실패는 해당 run만 fail 기록(전체 실험 안 죽음).

## Component 3 — 프롬프트·구조 개선 루프 (Phase 2, 메인 목적)

Phase 1(Component 1·2)이 붙으면 baseline 평가를 돌려 약점 클러스터를 찾고,
아래 레버를 고쳐 재평가 → before/after 비교로 개선을 확정한다. **어떤 프롬프트를
어떻게 고칠지는 baseline 결과에 따라 결정**되므로(데이터 주도) 고정 편집이 아니라
반복 프로토콜로 규정한다.

**방법론 정박 — 수집한 논문 5편 (`sft_pipeline/docs/idea/sft_citation.md`).**
현재 트리에서 revert됨(커밋 `2d352e9`에 원본, 복원 여부 별도 결정). 개선 축을
논문 원칙에 묶어 ad-hoc 편집을 막는다:

| 개선 축 | 관련 평가자 | 정박 논문 · 원칙 |
| --- | --- | --- |
| 날짜별 플랜 구조·정합성 | `structure_valid`, `plan_coherence`, `date_sanity` | **LLM-Modulo**(Kambhampati 2024): LLM은 "무엇을+상대배치"만, **절대 날짜 산수는 코드**(`allocator.py`), judge=**hard critic**. 프롬프트에 달력 계산을 넣지 않는다. self-verification 금지 → 검증은 외부(judge/코드). |
| 꼬리질문 여부(언제 물을까) | `plan_coherence`, `followup_appropriate` | **Clarify When Necessary**(3): 물을지/추측할지/거부할지. **Curiosity by Design**(5): under-specified면 먼저 되묻기. |
| 꼬리질문 내용(무엇을 물을까) | `followup_appropriate` | **What Prompts Don't Say**(4): 사람은 조건을 안 말한다 → 빠진 **최고가치 슬롯**을 묻게 `FOLLOW_UP_SYSTEM` 튜닝. |
| hard/soft 분리 검증 | 전체 | **LLM-Modulo 여행계획 사례**(2): hard(마감·중복금지)와 soft(선호)를 분리, backprompt 반복(≤10). 우리 evaluator를 hard/soft로 구분해 해석. |

원칙 위배 금지: 프롬프트로 LLM에게 날짜 산수를 시키는 방향(LLM-Modulo 반대),
self-critique로 자기교정 유도(논문상 무효) 등은 채택하지 않는다.

프롬프트 레버 (`adapters/todo_creation/_prompts.py`, EXAONE 어댑터 기준):

| 심볼 | 노드 | 개선 축 |
| --- | --- | --- |
| `REQUEST_CLASSIFIER_SYSTEM` | classify | 라우팅(일상/시험/event) |
| `PLANNER_JUDGE_SYSTEM` | judge | 충분성 판정 → 꼬리질문 여부 |
| `FOLLOW_UP_SYSTEM` | follow_up | 꼬리질문 질 |
| `PLAN_GENERATOR_SYSTEM` | plan_generator | 날짜별 플랜 구조·정확도 |
| `PLAN_VALIDATOR_SYSTEM` / `GOAL_TAG_SYSTEM` / `OUT_OF_SCOPE_REPLY_SYSTEM` | 각 노드 | 검증·태깅·범위밖 |

구조 레버: `planner/graph.py`(노드 배선), `planner/nodes/*`,
`planner/allocator.py`(날짜 분배), `planner/goal_rules.py`(plan_kind별 규칙).

반복 프로토콜(수정 1건당):
1. baseline 실험에서 낮은 점수 평가자/카테고리 식별(예: `korean_only` 저조,
   event 라우팅 오류, 성급한 플랜=`plan_coherence` 0).
2. 원인 가설 → 해당 프롬프트 심볼 또는 구조 파일 1곳만 수정(외과적).
3. 재평가(run_eval) → `compare.py`로 before→after delta 확인.
4. 개선이면 커밋(프롬프트 변경 diff + 실험 링크), 회귀면 되돌림.

주의: EXAONE는 guided_json/JSON 모드 거동이 Qwen과 다를 수 있으므로 프롬프트의
언어 지시(한국어 강제)·JSON 스키마 예시는 EXAONE 출력 실측으로 튜닝한다.

## 데이터 흐름

```
frontend형 PlannerInput
  → pipeline.run()
    → LangGraph (노드 자동 추적)
      → RunPod LLM (@traceable 추적)
    → PlannerResult
  → evaluators 채점
  → LangSmith experiment (URL)
```

## 에러 처리

- `init_langsmith()`: 키/플래그 없으면 조용히 no-op. 예외 던지지 않음.
- `@traceable` wrap: LLM 에러를 삼키거나 변형하지 않음. 재시도(RetryPolicy) 정상 동작.
- eval `target`: 예제별 try/except → 실패 run만 기록, 실험 계속.

## 테스트

- `evaluators.py`는 순수함수 → canned 출력으로 유닛테스트(각 evaluator당 pass/fail 1쌍).
- 스모크: 키 세팅 후 2~3 example로 `run_eval.py` 1회 → LangSmith에 트레이스·점수 확인.

## 미해결 / 확인 필요

- 라이브 RunPod 호출에는 `RUNPOD_*` 엔드포인트/키가 로컬 `.env`에 있어야 함
  (평가는 실제 배포를 때림). 키 만료 이력 있음 — 실행 전 확인.
- `judge_sufficiency` 시그니처를 evaluator 인터페이스에 맞추는 어댑터 필요.
