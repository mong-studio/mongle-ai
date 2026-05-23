# character_creation 파이프라인 LangGraph 재구현 설계

> 날짜: 2026-05-22
> 범위: `agents/character_creation/` 만 (다른 피처는 향후 별도 마이그레이션)
> 호환성: `agents.character_creation.pipeline.run(...)` 외부 시그니처 유지

---

## 1. 목적

현재 `character_creation` 파이프라인은 `asyncio.create_task` 기반의 명령형 오케스트레이션이다. 이를 LangGraph `StateGraph` 기반의 선언형 그래프로 재구현하여 다음 이점을 확보한다.

- **시각적 그래프/관찰성**: `graph.get_graph().draw_mermaid()` 및 노드 단위 트레이싱.
- **조건 분기/라우팅**: `router.decide()` 를 `conditional_edges` 로 선언적으로 표현.
- **노드 진행 이벤트 스트리밍**: `graph.astream_events()` 로 호출자가 노드 시작/완료 이벤트 구독 가능. (HITL interrupt 는 본 마이그레이션 범위 외)

체크포인팅/영속화는 본 마이그레이션 범위 외.

## 2. 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 마이그레이션 범위 | `character_creation` 만 |
| 접근 방식 | Approach B (풀 네이티브) — RetryPolicy + compensation 노드 |
| Ports / Protocol DI | 유지. `RunnableConfig.configurable["ports"]` 로 전달 |
| State | Pydantic `CharacterGraphState` (별도 `state.py`) |
| 재시도 정책 | LangGraph `RetryPolicy` 로 이관 (노드 내부 retry 루프 제거) |
| Cleanup | 그래프 내부 `cleanup_source_image` 노드 (compensation) |
| HITL | 본 범위 외 (구조만 호환되도록) |
| 외부 의존성 추가 | `langgraph>=0.2,<0.3` |
| 호환성 | `pipeline.run()` 시그니처 유지 |

## 3. State 스키마

```python
# agents/character_creation/state.py
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel
from agents.character_creation.schemas import (
    CharacterCreationInput, CharacterEntity,
    LLMPersonaResult, VLMResult,
)

Route = Literal["text_only", "image_and_text"]

class CharacterGraphState(BaseModel):
    # 입력 (불변)
    input: CharacterCreationInput
    is_regeneration: bool

    # 라우팅
    route: Route | None = None

    # 중간 산출물
    llm_result: LLMPersonaResult | None = None
    vlm_result: VLMResult | None = None
    source_url: str | None = None
    source_key: str | None = None
    image_bytes: bytes | None = None      # image_generator → generated_upload 사이 전달
    generated_url: str | None = None

    # 종료 산출물 (builder 노드에서 채움)
    entity: CharacterEntity | None = None

    # 오류 전파용 (compensation 분기 트리거)
    error: Exception | None = None

    model_config = {"arbitrary_types_allowed": True}
```

* 모든 필드는 노드의 부분 업데이트 결과로 채워진다.
* `entity` 가 채워지면 그래프 종료가 happy-path 였음을 의미한다.
* `error` 가 채워지면 cleanup 분기로 전이된다.
* `image_bytes` 는 `image_generator` → `generated_upload` 사이에서만 유효한 임시 필드다. 그래프 종료 시점에는 자연히 더 이상 참조되지 않으며 별도 cleanup 은 불필요하다.

## 4. 그래프 토폴로지

```
START
  │
  ▼
validate
  │  (conditional_edges, 라우팅 결과)
  ├── text_only       → ["llm_persona"]
  └── image_and_text  → ["llm_persona", "source_upload"]
                                          │
                                          ▼
                                     vlm_analyzer
                                          │
       ┌──────────────────────────────────┘
       ▼ (활성 inbound 채널 모두 도착 시 실행)
image_generator
  │  (conditional_edges: state.error ?)
  ├── ok    → generated_upload
  └── error → cleanup_source_image → END (raise)

generated_upload
  │  (conditional_edges)
  ├── ok    → builder
  └── error → cleanup_source_image → END (raise)

builder
  │  (conditional_edges)
  ├── ok    → END
  └── error → cleanup_source_image → END (raise)
```

### 4.1 노드별 책임

| 노드 | 책임 | 부분 업데이트 키 |
|---|---|---|
| `validate` | `validation.check()` 호출 + `route` 결정 | `route` |
| `llm_persona` | LLM 페르소나 1회 호출 (retry 는 RetryPolicy) | `llm_result` |
| `source_upload` | 원본 이미지 S3 업로드 1회 (retry 는 RetryPolicy) | `source_url`, `source_key` |
| `vlm_analyzer` | VLM 외모 추출. 노드 내부에서 재시도 후 실패 시 `None` 폴백 | `vlm_result` |
| `image_generator` | 캐릭터 이미지 생성 1회 + counter.increment | `image_bytes` 또는 `error` |
| `generated_upload` | 생성 이미지 S3 업로드 1회 | `generated_url` 또는 `error` |
| `builder` | 최종 `CharacterEntity` 조립 | `entity` 또는 `error` |
| `cleanup_source_image` | `source_key` 있으면 삭제, 그 후 `state.error` 재발생 | — (raise) |

### 4.2 라우팅 함수

```python
# agents/character_creation/router.py
def decide(state: CharacterGraphState) -> list[str]:
    if state.input.source_image is not None:
        return ["llm_persona", "source_upload"]
    return ["llm_persona"]
```

기존 `RouteDecision` Enum 은 `state.route` (`Literal`) 로 흡수하여 제거한다.

### 4.3 Fan-in 동작

`image_generator` 는 inbound 엣지가 `llm_persona`, `vlm_analyzer` 두 곳에서 들어온다.
LangGraph 의 기본 동작상 `validate → conditional_edges` 가 `source_upload` 를 활성화하지 않으면 `vlm_analyzer` 도 활성화되지 않고, `image_generator` 는 `llm_persona` 만 완료되어도 실행된다.

## 5. Retry 정책

각 노드는 `add_node(name, fn, retry=RetryPolicy(...))` 로 등록.

| 노드 | max_attempts | retry_on |
|---|---|---|
| `llm_persona` | 3 | `LLMFailedError` |
| `source_upload` | 4 | `S3UploadFailedError` |
| `vlm_analyzer` | 노드 내부 try/except 3회 (실패 시 `vlm_result=None` 반환, 그래프 진행) | — |
| `image_generator` | 2 | `ImageGenerationFailedError` |
| `generated_upload` | 4 | `S3UploadFailedError` |

`vlm_analyzer` 는 "최종 실패 시 None 으로 폴백" 의미가 RetryPolicy 만으로 표현되지 않으므로, 노드 본문에서 명시적 try/except 루프 유지.

## 6. Cleanup (Compensation) 정책

* `image_generator`, `generated_upload`, `builder` 세 노드를 try/except 로 감싼다.
* 예외 발생 시: `state.error` 에 예외 인스턴스 기록 후 정상 `dict` 반환.
* 각 노드 다음 엣지를 `conditional_edges` 로 분기:
  * `state.error is None` → 다음 happy-path 노드
  * `state.error is not None` → `cleanup_source_image`
* `cleanup_source_image` 노드:
  ```python
  async def cleanup_source_image(state, config):
      ports = config["configurable"]["ports"]
      if state.source_key:
          await ports.repository.delete_image_keys([state.source_key])
      raise state.error
  ```
* `cleanup_source_image` 에서 raise 한 예외가 `graph.ainvoke()` 호출자에게 그대로 전파된다.

`validate`, `llm_persona`, `source_upload`, `vlm_analyzer` 단계의 실패는 cleanup 이 필요 없다. `source_upload` 가 RetryPolicy 소진 후 raise 하면 `source_key` 는 state 에 채워지지 않은 채 예외가 전파된다.

## 7. Ports 전달

* 외곽 `run()` 에서 `config={"configurable": {"ports": ports, "now": now}}` 전달.
* 각 노드는 `config["configurable"]["ports"]` 로 Port 접근.
* `protocols.py` 자체는 변경 없음.

## 8. 외곽 `run()` 시그니처

```python
# agents/character_creation/pipeline.py
async def run(
    input: CharacterCreationInput,
    *,
    ports: Ports,
    is_regeneration: bool,
    now: datetime | None = None,
) -> CharacterEntity:
    state = CharacterGraphState(input=input, is_regeneration=is_regeneration)
    config = {"configurable": {"ports": ports, "now": now}}
    final: CharacterGraphState = await graph.ainvoke(state, config=config)
    assert final.entity is not None
    return final.entity
```

기존 호출자(예: API 핸들러, 테스트) 의 변경 불필요.

## 9. 파일 구조 변화

```
agents/character_creation/
├── __init__.py
├── pipeline.py            ← run() 외곽 함수만 유지
├── graph.py               ← NEW: StateGraph 정의 + 컴파일
├── state.py               ← NEW: CharacterGraphState
├── router.py              ← decide(state) -> list[str] 로 시그니처 변경
├── protocols.py           ← 변경 없음
├── schemas.py             ← 변경 없음
├── exceptions.py          ← 변경 없음
├── validation.py          ← 변경 없음
├── repository.py          ← 변경 없음
└── nodes/
    ├── __init__.py
    ├── validate.py        ← NEW: validation.check 래핑
    ├── llm_persona.py     ← retry 루프 제거, 단일 호출
    ├── vlm_analyzer.py    ← 노드 내부 try/except 폴백 유지
    ├── source_upload.py   ← NEW (image_upload._put_object 래핑)
    ├── generated_upload.py← NEW (image_upload._put_object 래핑)
    ├── image_upload.py    ← _key_for, _put_object helper 만 유지 (retry 제거)
    ├── image_generator.py ← retry 루프 제거, counter.increment 유지
    ├── builder.py         ← state 기반 노드 시그니처로 래퍼 추가, helper 유지
    └── cleanup.py         ← NEW: cleanup_source_image
```

각 노드 모듈은 내부에 (a) 순수 helper, (b) LangGraph 노드 함수 두 계층으로 구성한다.
helper 함수는 기존 단위 테스트가 그대로 붙는다.

## 10. 테스트 영향

| 테스트 | 변경 |
|---|---|
| `validation.check` | 변경 없음 |
| `nodes/llm_persona` retry 카운트 | **삭제** — RetryPolicy 이관 |
| `nodes/vlm_analyzer` retry → None 폴백 | **유지** (노드 내부 폴백 로직 유지) |
| `nodes/image_upload` retry | **삭제** — RetryPolicy 이관 |
| `nodes/image_generator` retry | **삭제** — RetryPolicy 이관 |
| `nodes/builder` helper 테스트 | 변경 없음 |
| `pipeline.run` 통합 테스트 | **재작성** — `graph.ainvoke` 기반 |
| 신규: RetryPolicy 동작 그래프 테스트 | 추가 (`LLMFailedError` 3회 시 raise, 2회+성공 시 결과 반환) |
| 신규: cleanup compensation 그래프 테스트 | 추가 (image_generator 실패 시 `source_key` 삭제 검증) |
| 신규: 라우팅 그래프 테스트 | 추가 (TEXT_ONLY 시 vlm_analyzer 미호출) |

커버리지 80% 라인 유지 (폐기 + 추가 상쇄).

## 11. 의존성

`pyproject.toml`:

```toml
dependencies = [
    "pydantic>=2.6,<3",
    "boto3>=1.34",
    "langgraph>=0.2,<0.3",   # ADD
]
```

LangChain 본체는 추가하지 않는다. LLM/VLM 호출은 기존 Port 추상화 사용.

## 12. 문서 영향

- `docs/features/character_generation/CLAUDE.md`: 파이프라인 섹션을 LangGraph 토폴로지로 갱신.
- `docs/features/character_generation/architecture.mmd`: as-built 갱신 (`FEATURES.md` §4 DoD).
- `CHANGELOG.md`: "character_creation 파이프라인 LangGraph 기반 재구현" 항목 추가.
- `CLAUDE.md` 라우팅 테이블의 캐릭터 생성 행은 변경 불필요 (피처 폴더 `CLAUDE.md` 가 정문).

## 13. 비범위 (Out of Scope)

- 체크포인터/영속화 (SqliteSaver 등).
- HITL interrupt.
- 다른 피처 (todo, quest_generation, feed_generation) 의 마이그레이션.
- LLM/VLM 어댑터 자체 교체. Port 만 유지하면 어댑터는 무관.

## 14. 성공 기준 (DoD)

1. 기존 `pipeline.run()` 호출자가 코드 변경 없이 동작한다.
2. `pytest` 통과, 커버리지 ≥ 80%.
3. TEXT_ONLY / IMAGE_AND_TEXT 두 경로의 통합 테스트 모두 통과.
4. `image_generator` 실패 시 source 이미지 삭제 호출이 발생함을 검증하는 테스트 통과.
5. `vlm_analyzer` 전 시도 실패 시 그래프가 진행되어 `vlm_result=None` 으로 `image_generator` 가 호출됨을 검증하는 테스트 통과.
6. RetryPolicy 동작 검증 테스트 통과 (`LLMFailedError` 3회 시 raise, 2회+성공 시 결과 반환).
7. `docs/features/character_generation/architecture.mmd` as-built 갱신.
8. `CHANGELOG.md` 항목 추가.
