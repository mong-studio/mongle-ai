# Feed Generation Pipeline — Design Spec

**Date:** 2026-05-27  
**Status:** Approved  
**Scope:** `agents/feed_generation/` + `adapters/feed_generation/`  
**Out of scope:** VLM(비전 언어 모델) — 이미지 분석 없음

---

## 1. 목표

퀘스트 완료 시 캐릭터 이미지와 한글 캡션으로 구성된 피드를 생성한다.

- 이미지: 캐릭터 기준 이미지(Img2Img) + 퀘스트 텍스트 프롬프트 → S3 업로드 → URL 반환
- 캡션: 퀘스트 내용 + 캐릭터 페르소나 → LLM(Mi:dm) → 한국어 ≤140자

---

## 2. 입출력 스키마

```python
class QuestRef(BaseModel):
    quest_id: UUID
    quest_text: str

class CharacterRef(BaseModel):
    character_id: UUID
    name: str
    personality: str
    speech_style: str
    appearance_keywords: list[str]
    image_url: str          # Img2Img 기준 이미지 (character_creation S3 URL)

class FeedGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest: QuestRef
    character: CharacterRef

class GeneratedFeed(BaseModel):
    character_id: UUID
    quest_id: UUID
    image_url: str          # S3 업로드 후 URL
    caption: Annotated[str, Field(max_length=140)]
```

**변경점 (CLAUDE.md 대비):**
- `CharacterRef.image_url` 추가 — Img2Img 기준 이미지 전달용
- `GeneratedFeed.image: bytes | str` → `image_url: str` — S3 URL 반환으로 확정

---

## 3. Ports

```python
class LLMPort(Protocol):
    async def generate(self, prompt: str) -> str: ...

class ImageGeneratorPort(Protocol):
    async def generate_img2img(
        self,
        reference_url: str,
        prompt: str,
    ) -> bytes: ...

class S3Port(Protocol):
    async def upload(self, key: str, data: bytes) -> str: ...  # returns URL

@dataclass
class Ports:
    llm: LLMPort
    image_generator: ImageGeneratorPort
    s3: S3Port
```

`ImageGeneratorPort` 시그니처는 `character_creation`의 것과 동일하게 맞춰 어댑터 공유를 허용한다.  
Repository 포트 없음 — 피드 저장은 호출자(commit 레이어)가 담당한다.

---

## 4. 파이프라인 아키텍처

### 4.1 노드 흐름

```
validate
  → assemble_image_prompt
    → img2img
      → s3_upload
        → assemble_caption_ctx
          → llm_caption
            → validate_caption
              → builder
```

직렬 실행. 이미지 생성이 완료된 후 캡션 컨텍스트 조립 시작.

### 4.2 LangGraph State

```python
class FeedGraphState(TypedDict):
    input: FeedGenerationInput
    image_prompt: str | None
    raw_image: bytes | None
    image_url: str | None
    caption_ctx: str | None
    raw_caption: str | None
    result: GeneratedFeed | None
```

### 4.3 노드 상세

| 노드 | 책임 | 입력 상태 필드 | 출력 상태 필드 | RetryPolicy |
|------|------|----------------|----------------|-------------|
| `validate` | 입력 유효성 검사 | `input` | — | 없음 |
| `assemble_image_prompt` | 캐릭터 키워드 + 퀘스트 텍스트로 이미지 프롬프트 조립 | `input` | `image_prompt` | 없음 |
| `img2img` | 기준 이미지 + 프롬프트 → 이미지 바이트 | `input.character.image_url`, `image_prompt` | `raw_image` | max_attempts=3 |
| `s3_upload` | 이미지 바이트 → S3 업로드 | `raw_image` | `image_url` | max_attempts=3 |
| `assemble_caption_ctx` | 퀘스트 + 캐릭터 페르소나 + 이미지 프롬프트로 캡션 컨텍스트 조립 | `input`, `image_prompt` | `caption_ctx` | 없음 |
| `llm_caption` | LLM(Mi:dm)으로 한국어 캡션 생성 | `caption_ctx` | `raw_caption` | max_attempts=3 |
| `validate_caption` | 한국어 포함 여부 + 140자 이하 검사 | `raw_caption` | — | 없음 |
| `builder` | 최종 GeneratedFeed 조립 | `input`, `image_url`, `raw_caption` | `result` | 없음 |

---

## 5. 에러 핸들링

모든 실패 → 피드 미생성(예외 전파). 부분 피드 없음.

```python
class FeedGenerationError(Exception): ...
class InputValidationError(FeedGenerationError): ...
class ImageGenerationError(FeedGenerationError): ...   # img2img 3회 실패
class S3UploadError(FeedGenerationError): ...          # S3 3회 실패
class CaptionGenerationError(FeedGenerationError): ... # LLM 3회 실패
class CaptionValidationError(FeedGenerationError): ... # 한국어 미포함 or >140자
```

`validate_caption` 실패 시 재시도 없음 — LLM 프롬프트 문제이므로 호출자로 전파.

**캡션 검증 규칙:**
- `len(caption) > 140` → `CaptionValidationError`
- `가`–`힣` 범위 문자 없음 → `CaptionValidationError`

---

## 6. 파일 구조

```
agents/feed_generation/
├── pipeline.py               # async run(input, *, ports) → GeneratedFeed
├── graph.py                  # LangGraph StateGraph 정의
├── state.py                  # FeedGraphState TypedDict
├── schemas.py                # QuestRef, CharacterRef, FeedGenerationInput, GeneratedFeed
├── protocols.py              # LLMPort, ImageGeneratorPort, S3Port, Ports
├── exceptions.py
├── debug.py
└── nodes/
    ├── validate.py
    ├── assemble_image_prompt.py
    ├── img2img.py
    ├── s3_upload.py
    ├── assemble_caption_ctx.py
    ├── llm_caption.py
    ├── validate_caption.py
    └── builder.py

adapters/feed_generation/
└── midm_llm.py               # Mi:dm LLMPort 구현
```

---

## 7. 제약 조건 (AI_RULES.md 준수)

- C1: 캡션 언어 = 한국어
- C2: 캡션 길이 ≤ 140자
- C3: 캡션 톤이 `speech_style` 반영
- C4: 캡션 내용이 퀘스트 내용 연관
- C5: 이미지가 캐릭터의 퀘스트 수행 장면 묘사
- VLM 미사용 → C6(이미지↔캡션 일관성)은 프롬프트 공유로 대응 (`image_prompt`를 캡션 컨텍스트에도 전달)

---

## 8. 테스트 전략

- 각 노드를 독립 단위 테스트 (포트 mock)
- `validate_caption`: 경계값 테스트 (140자, 141자, 한국어 없는 케이스)
- `pipeline.run()` 통합 테스트: 모든 포트 mock → `GeneratedFeed` 반환 검증
- 실패 경로: img2img 3회 실패 → `ImageGenerationError` 전파 검증
