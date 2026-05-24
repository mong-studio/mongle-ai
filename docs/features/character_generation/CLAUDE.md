# 캐릭터 생성 AI Agent 설계서

**관련 문서:**
- 제품 컨텍스트: [../../PRODUCT_SPEC.md](../../PRODUCT_SPEC.md)
- 피처 인덱스·공통 패턴·DoD: [../../FEATURES.md](../../FEATURES.md)
- 공통 AI 규칙: [../../AI_RULES.md](../../AI_RULES.md)
- 데이터 모델: [../../DATA_MODEL.md](../../DATA_MODEL.md) — §2 (캐릭터), §6.3 (img_gen_logs)
- 아키텍처 다이어그램: [./architecture.mmd](./architecture.mmd)

---

> 몽글마을 — 캐릭터 생성 파이프라인 하네스(Harness) 구조 작성을 위한 참고 문서.

---

## 1. 목적 (Goal)

사용자가 업로드한 애착 인형 이미지 및/또는 입력한 텍스트(페르소나, 성격 키워드)를 바탕으로, **8bit 픽셀 스타일 정면 캐릭터 이미지**와 **캐릭터 메타데이터(성격, 말투, 배경)**를 생성하여 DB에 영속화한다.

생성된 캐릭터는 이후 퀘스트 생성, 알림 텍스트, 피드 생성 등에 재사용된다.

---

## 2. 입력 / 출력 (I/O Contract)

### 2.1 Input

| 필드                   | 타입              | 필수 | 비고                         |
| ---------------------- | ----------------- | ---- | ---------------------------- |
| `user_id`              | string            | ✅   | 인증된 사용자 식별자         |
| `persona`              | string (textarea) | ✅   | 캐릭터 설명 / 페르소나       |
| `name`                 | string            | ✅   | 캐릭터 이름                  |
| `personality_keywords` | string[]          | ❌   | pill 선택, 최대 3개          |
| `source_image`         | File              | ❌   | JPG / PNG / JPEG, ≤ 5MB, 1개 |

**성격 키워드 enum** (12종):
`모험적인`, `차분한`, `호기심많은`, `다정한`, `장난스러운`, `부지런한`, `강력한`, `몽환적인`, `분노가 많은`, `용감한`, `온화한`, `명랑한`

### 2.2 Output

```json
{
  "character_id": "uuid",
  "name": "몽글이",
  "persona": "...",
  "personality": "...",
  "speech_style": "...",
  "background": "...",
  "image_url": "https://s3.../characters/{uuid}.png",
  "source_image_url": "https://s3.../sources/{uuid}.png | null",
  "created_at": "ISO8601"
}
```

---

## 3. 제약사항 (Constraints)

| ID  | 항목                    | 값                                                      |
| --- | ----------------------- | ------------------------------------------------------- |
| C1  | 캐릭터 보유 상한        | 계정당 **10개**                                         |
| C2  | 이미지 재생성 일일 제한 | 계정당 **3회** / 당일 최초 생성 기준 24시간 이후 초기화 |
| C3  | 업로드 이미지 형식      | JPG, PNG, JPEG                                          |
| C4  | 업로드 이미지 크기      | **≤ 5MB**, 1회 1개                                      |
| C5  | DB 저장 대상            | 캐릭터 빌드 결과 + LLM 생성 결과만 (중간 산출물 제외)   |
| C6  | 출력 스타일             | **8bit 픽셀 정면 이미지** (스타듀밸리 톤)               |

이 제약은 파이프라인 진입 전 **Validation 단계에서 모두 검사**한다. 위반 시 에이전트를 실행하지 않고 즉시 에러를 반환한다.

---

## 4. 노드별 책임 (Node Responsibilities)

### 4.1 Validation

- **Input:** validated `CharacterCreationInput` (백엔드가 C1·C2 를 이미 통과시킨 상태)
- **검사 항목:**
  - C3, C4: 이미지 MIME 타입 및 바이트 크기 (source_image 가 있을 때만)
  - 필수 필드(persona, name) 존재 여부는 Pydantic 스키마(`CharacterCreationInput`)에서 처리
- **실패 시:** `ValidationFailedError(code=...)` 즉시 raise → 파이프라인 미실행
- **부수효과:** 없음 (read-only, 레포지토리 호출 없음)

> C1(보유 상한)·C2(일일 재생성 제한)은 **에이전트의 책임이 아니다**. 백엔드(호출자)가 사전 검증해야 하며, `CharacterRepositoryPort` 는 이를 위한 메서드를 노출하지 않는다.

### 4.2 Input Type Router

- **Input:** validated input
- **분기 기준:** `source_image` 존재 여부
  - 없음 → Text Pipeline만
  - 있음 → Image Pipeline + Text Pipeline (병렬 가능)
- **참고:** 텍스트 파이프라인은 두 경로 모두에서 항상 실행됨

### 4.3 Text Pipeline (LLM)

- **모델:** LLM (모델 선택은 별도 결정)
- **Input:** `persona`, `personality_keywords`
- **Output:**
  ```json
  {
    "personality": "...",
    "speech_style": "...",
    "background": "..."
  }
  ```
- **제약:** 출력은 항상 위 JSON 스키마 준수 (구조화 출력 강제)

### 4.4 Image Pipeline

- **Input:** `source_image`
- **부수효과:** 원본 이미지를 S3에 저장 (key: `sources/{user_id}/{uuid}.{ext}`)
- **Output:** S3 URL + raw image bytes (다음 단계로 전달)

### 4.5 VLM / Image Analyzer

- **실행 조건:** 이미지 입력이 있는 경우에만
- **목적:** 원본 특징(색상, 형태, 질감 등) 추출 → 생성 이미지의 정체성 유지
- **Output:** 자연어 외형 묘사 (e.g. "둥근 갈색 곰, 빨간 리본, 큰 눈")

### 4.6 캐릭터 이미지 생성

- **Input:** LLM 결과(성격/말투/배경) + VLM 외형 특징 (이미지 입력 시) + (텍스트만 입력 시 페르소나)
- **Output:** 8bit 픽셀 정면 캐릭터 이미지
- **부수효과:** 생성 이미지를 S3에 저장 (key: `characters/{user_id}/{uuid}.png`)
- **블랙박스 단계:** 내부 구현은 별도(Img2Img / Text2Img 파이프라인). 하네스 관점에서는 단일 단계로 추상화.

### 4.7 캐릭터 빌드

- **Input:** LLM 결과 + VLM 결과(있을 시) + 생성 이미지 URL + 원본 메타데이터(name, persona)
- **Output:** DB 저장 가능한 캐릭터 엔티티 객체
- **책임:** 산출물을 단일 도메인 객체로 조립. 누락 필드 검증.

### 4.8 Character DB 저장

- **저장 대상 (C5):** 캐릭터 빌드 결과 + LLM 생성 결과만
- **저장하지 않음:** 중간 산출물(Canny 엣지, 임시 마스크 등)

---

## 5. 하네스(Harness) 구조 가이드

Claude Code가 코드 작성 시 따를 권장 구조.

### 5.1 디렉토리 레이아웃 (LangGraph 마이그레이션 후)

```
agents/character_creation/
├── __init__.py
├── pipeline.py             # run() entry — graph.ainvoke 위임
├── graph.py                # StateGraph 정의 + 컴파일 (build_graph)
├── state.py                # CharacterGraphState (Pydantic)
├── validation.py           # 4.1 검증 헬퍼 (validate_node 가 호출)
├── router.py               # decide(state) -> list[str] (text_only=vlm_analyzer 직행, image_and_text=source_upload 경유, graph.py 에서 import)
├── protocols.py            # Port 인터페이스 (변경 없음)
├── nodes/
│   ├── validate.py         # 4.1 validate_node
│   ├── llm_persona.py      # 4.3 llm_persona_node (1회 호출, retry 는 RetryPolicy)
│   ├── source_upload.py    # 4.4 source_upload_node (retry 는 RetryPolicy)
│   ├── vlm_analyzer.py     # 4.5 vlm_analyzer_node (내부 3회 retry + None 폴백)
│   ├── image_upload.py     # key_for / put_once 헬퍼만
│   ├── image_generator.py  # 4.6 image_generator_node (내부 2회 retry + state.error 기록)
│   ├── generated_upload.py # 생성 이미지 업로드 노드 (내부 4회 retry + state.error 기록)
│   ├── builder.py          # 4.7 build() 헬퍼 + builder_node
│   └── cleanup.py          # cleanup_source_image_node (compensation)
├── repository.py           # 4.8 DB I/O
├── schemas.py              # Pydantic 모델 (Input/Output/중간 산출물)
└── exceptions.py           # 도메인 예외
```

### 5.2 인터페이스 스케치

```python
# schemas.py
class CharacterCreationInput(BaseModel):
    user_id: str
    name: str
    persona: str
    personality_keywords: list[PersonalityKeyword] = Field(default_factory=list, max_length=3)
    source_image: UploadFile | None = None

class LLMPersonaResult(BaseModel):
    personality: str
    speech_style: str
    background: str

class VLMResult(BaseModel):
    appearance_description: str

class CharacterEntity(BaseModel):
    character_id: UUID
    user_id: str
    name: str
    persona: str
    personality: str
    speech_style: str
    background: str
    image_url: str
    source_image_url: str | None
    created_at: datetime

# pipeline.py — LangGraph 위임
_GRAPH = build_graph()

async def run(
    input: CharacterCreationInput,
    *,
    ports: Ports,
    now: datetime | None = None,
) -> CharacterEntity:
    initial = CharacterGraphState(input=input)
    final = await _GRAPH.ainvoke(
        initial, config={"configurable": {"ports": ports, "now": now}}
    )
    entity = final["entity"] if isinstance(final, dict) else final.entity
    assert entity is not None
    return entity

# graph.py 핵심
def build_graph():
    g = StateGraph(CharacterGraphState)
    g.add_node("validate", validate_node)
    g.add_node("llm_persona", llm_persona_node,
               retry=RetryPolicy(max_attempts=3, retry_on=LLMFailedError))
    g.add_node("source_upload", source_upload_node,
               retry=RetryPolicy(max_attempts=4, retry_on=S3UploadFailedError))
    g.add_node("vlm_analyzer", vlm_analyzer_node)        # source_image 없으면 즉시 None, 있으면 내부 3회 retry + None 폴백
    g.add_node("image_generator", image_generator_node)  # 내부 2회 retry + 소진 시 state.error
    g.add_node("generated_upload", generated_upload_node)  # 내부 4회 retry + 소진 시 state.error
    g.add_node("builder", builder_node)
    g.add_node("cleanup_source_image", cleanup_source_image_node)

    g.add_edge(START, "validate")
    g.add_conditional_edges("validate", decide)
    g.add_edge("source_upload", "vlm_analyzer")
    g.add_edge("llm_persona", "image_generator")
    g.add_edge("vlm_analyzer", "image_generator")
    g.add_conditional_edges("image_generator",  _ok_or_cleanup("generated_upload"))
    g.add_conditional_edges("generated_upload", _ok_or_cleanup("builder"))
    g.add_conditional_edges("builder",          _ok_or_cleanup_end)
    g.add_edge("cleanup_source_image", END)
    return g.compile()
```

오케스트레이션은 선언적 그래프이며, 노드 단위 retry 는 `RetryPolicy` 에 위임, 실패 시 source 이미지 cleanup 은 `cleanup_source_image_node` (compensation) 가 담당한다. 호출자 코드 변경은 없다.

---

## 6. 에러 처리 (Error Handling)

| 단계                  | 재시도                                                | 실패 시 처리                                                                          |
| --------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Validation            | 없음                                                  | `ValidationFailedError` 즉시 raise — 파이프라인 미실행                                |
| `llm_persona`         | `RetryPolicy(max_attempts=3, LLMFailedError)`         | 소진 시 raise → 그래프 ainvoke 호출자로 전파                                          |
| `source_upload`       | `RetryPolicy(max_attempts=4, S3UploadFailedError)`    | 소진 시 raise → 그래프 ainvoke 호출자로 전파 (cleanup 불필요, source_key 미저장)      |
| `vlm_analyzer`        | 노드 내부 3회                                         | 모든 시도 실패 시 `vlm_result=None` 으로 그래프 진행 (degrade-on-fail)                |
| `image_generator`     | 노드 내부 2회 (`ImageGenerationFailedError`)          | 소진 시 `state.error` 기록 → `cleanup_source_image_node` 분기 → `S3Port.delete_object(state.source_key)` 후 raise |
| `generated_upload`    | 노드 내부 4회 (`S3UploadFailedError`)                 | 소진 시 `state.error` 기록 → `cleanup_source_image_node` 분기 → `S3Port.delete_object(state.source_key)` 후 raise |
| `builder`             | 없음                                                  | 예외 시 `state.error` 기록 → `cleanup_source_image_node` 분기 → `S3Port.delete_object(state.source_key)` 후 raise |

**원자성:** 캐릭터 이미지가 S3에 저장된 뒤 DB 저장이 실패하면 고아 파일이 남는다. 트랜잭션 outbox 패턴 또는 정기 cleanup 잡으로 처리할지 결정 필요.

---

## 7. 결정 사항 (Resolved)

본 피처 첫 구현(`agents/character_creation/`) 시점에 다음과 같이 결정되었다. 코드 결정은 `agents/character_creation/decisions.md` 참조.

1. **이미지 생성 모델 선택** — 단일 `ImageGeneratorPort` Protocol. text-only / image-input 분기는 어댑터 내부 책임.
2. **재생성 카운트 정의** — 이미지 생성 호출 1회 = 재생성 1회. 호출 직전 `img_gen_logs.gen_cnt` +1 (재시도는 카운트하지 않음).
3. **VLM 실패 시 정책** — degrade-on-fail. 재시도 2회 모두 실패 시 외형 정보 없이 LLM 결과 + 페르소나 텍스트로 진행.
4. **병렬 처리 범위** — LLM 과 VLM 은 `asyncio.gather` 로 병렬. S3 원본 업로드는 VLM 직전에 순차.
5. **이미지 생성 프롬프트 조립** — `ImageGenerator.generate` 어댑터 내부에서 조립. 파이프라인은 구조화 입력만 전달.

---

## 8. 참고

- 본 문서는 **하네스/오케스트레이션 레이어** 설계를 위한 것이며, 각 AI 모델의 내부 구현(예: ControlNet 파이프라인의 디테일)은 다루지 않는다.
- DB 스키마, 인증, 결제(토큰 차감)는 별도 문서.
