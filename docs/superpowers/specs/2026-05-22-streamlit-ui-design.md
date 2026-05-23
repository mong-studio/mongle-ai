# Streamlit UI for character_creation — Design Spec

**작성일:** 2026-05-22
**대상 피처:** `agents/character_creation`
**상태:** 설계 승인 완료 (사용자 YES)

---

## 1. 목적

`character_creation` 파이프라인을 브라우저에서 직접 실행해 입력/중간 산출물/최종 결과(LLM 페르소나·VLM 외형 분석·생성 이미지)를 시각적으로 확인할 수 있는 개발자/데모용 Streamlit UI를 구축한다.

- **In scope:** `character_creation` 파이프라인 전용
- **Out of scope:** todo, quest_generation, feed_generation (이번 작업에선 다루지 않음)

## 2. 배경

`agents/character_creation`는 6개 Port(`LLMPort`, `VLMPort`, `S3Port`, `ImageGeneratorPort`, `RegenerationCounterPort`, `CharacterRepositoryPort`)를 `Protocol`로만 정의하고 구현체가 없다. 파이프라인 코드는 완성됐지만 실행 경로가 없어 동작 검증이 어렵다. Streamlit UI는 실제 어댑터를 주입해 end-to-end 실행을 가능케 한다.

## 3. 아키텍처

```
streamlit_app/         ← UI 레이어 (신규)
   │  Ports 조립 후 주입
   ▼
adapters/character_creation/   ← Port protocol 구현체 (신규)
   │
   ▼
agents/character_creation/     ← 기존 파이프라인 (변경 없음)
```

### 3.1 외과적 변경 원칙

기존 `agents/character_creation/**`의 어떤 파일도 수정하지 않는다. 모든 신규 코드는 `adapters/`, `streamlit_app/`, `src/prompts/character_creation/` 아래에 추가한다.

## 4. 신규 디렉토리 레이아웃

```
adapters/character_creation/
├── __init__.py
├── openai_llm.py         # LLMPort — gpt-4o + Structured Outputs (json_schema)
├── openai_vlm.py         # VLMPort — gpt-4o (multimodal, image_url base64)
├── openai_image.py       # ImageGeneratorPort — gpt-image-1, b64 → bytes
├── s3_storage.py         # S3Port — boto3 put_object + presigned GET URL
└── memory_repo.py        # CharacterRepositoryPort + RegenerationCounterPort (dict 백엔드)

src/prompts/character_creation/
├── llm_persona_v1.md     # 시스템 프롬프트 — 페르소나·말투·배경 JSON 생성 지시
├── vlm_appearance_v1.md  # 시스템 프롬프트 — 외형 한 문단 추출 지시
└── image_gen_v1.md       # 이미지 생성 프롬프트 — "8bit pixel art, front-facing" 스타일 가드

streamlit_app/
├── __init__.py
├── app.py                # streamlit 진입점 (실행: `streamlit run streamlit_app/app.py`)
└── ports_factory.py      # env + st.session_state → Ports dataclass 조립

tests/adapters/character_creation/
├── __init__.py
├── test_openai_llm.py
├── test_openai_vlm.py
├── test_openai_image.py
├── test_s3_storage.py
└── test_memory_repo.py
```

## 5. 어댑터 상세

### 5.1 `openai_llm.py` (LLMPort)

- 모델: `gpt-4o`
- 호출: `client.chat.completions.create(...)`, `response_format={"type":"json_schema", "json_schema": {...}, "strict": True}`
- 스키마: `LLMPersonaResult.model_json_schema()` 그대로 전달 (AI_RULES §2 구조화 출력 강제)
- 사용자 입력 격리: 시스템 프롬프트는 `llm_persona_v1.md`에서 로드, 사용자 `persona`·`keywords`는 별도 `user` 메시지의 "DATA:" 섹션에 격리 (AI_RULES §9)
- 실패 처리: 호출 실패·JSON 파싱 실패 시 `LLMFailedError` 발생 → 노드의 재시도(MAX_RETRIES=2)에 의존

### 5.2 `openai_vlm.py` (VLMPort)

- 모델: `gpt-4o`
- 이미지 전달: `image_url` 컨텐츠 블록 + `data:image/{ext};base64,{b64}` 형식
- 입력 검증: 5MB 초과 시 `VLMFailedError` (Anthropic이 아닌 OpenAI 한도는 20MB이지만 일관성 위해 5MB 유지)
- 출력: `VLMResult(appearance_description=...)` — 한 문단의 외형 설명, JSON 스키마 강제
- 실패 처리: `VLMFailedError` → 노드는 외형 정보 없이 진행하는 정책

### 5.3 `openai_image.py` (ImageGeneratorPort)

- 모델: `gpt-image-1`
- 호출: `client.images.generate(model="gpt-image-1", prompt=..., size="1024x1024", response_format="b64_json")`
- 프롬프트 조립:
  - `image_gen_v1.md`의 베이스 스타일 가드 (8bit pixel art, front-facing, transparent background 등)
  - + LLM 결과의 `personality`·`background` 요약
  - + (있다면) VLM 결과의 `appearance_description`
  - + (VLM 없을 때) `fallback_persona` 텍스트
- 응답: `data[0].b64_json` → `base64.b64decode(...)` → `bytes` 반환
- 실패 처리: `ImageGenerationFailedError` → 노드의 재시도(MAX_RETRIES=1)에 의존

### 5.4 `s3_storage.py` (S3Port)

- 클라이언트: `boto3.client("s3", region_name=AWS_REGION)`
- 업로드: `put_object(Bucket=AWS_S3_BUCKET, Key=key, Body=body, ContentType=content_type)`
- 반환값: presigned GET URL (`generate_presigned_url("get_object", ExpiresIn=3600)`) — Streamlit에서 즉시 표시 가능
- 키 prefix: `AWS_S3_PREFIX` 환경변수 + 노드에서 만든 `sources/{user}/...` / `characters/{user}/...` 결합
- 실패 처리: `botocore.exceptions.ClientError` → `S3UploadFailedError`로 래핑

### 5.5 `memory_repo.py` (CharacterRepositoryPort + RegenerationCounterPort)

- 백엔드: 모듈 레벨 dict가 아니라 **인스턴스 dict** (Streamlit `st.session_state`에 인스턴스를 보관해 사용자별 격리)
- 상태:
  - `_characters: dict[str, list[CharacterEntity]]` (user_id → 목록)
  - `_today_regen: dict[str, int]`
  - `_image_keys: set[str]` (rollback용)
- 메서드:
  - `count_active(user_id)` → 리스트 길이
  - `today_regen_count(user_id)` → counter
  - `save(entity)` → 리스트에 append
  - `delete_image_keys(keys)` → set에서 제거 (실제 S3 삭제는 별도 어댑터 책임이지만 데모에선 no-op 로그만)
  - `increment(user_id)` → counter += 1, 반환
- Streamlit 재시작 시 휘발 — 의도된 동작

## 6. Streamlit UI 화면

### 6.1 사이드바

- **user_id** (`st.text_input`, 기본 `demo-user`)
- **재생성 카운터**: `오늘 재생성 {n}/3` — `memory_repo.today_regen_count(user_id)`
- **보유 캐릭터**: `{n}/10` — `memory_repo.count_active(user_id)`
- **모드 토글** (선택): "재생성" 체크박스 → `is_regeneration` 인자

### 6.2 본문 — 입력 폼 (`st.form`)

| 위젯 | 필드 | 제약 |
|---|---|---|
| `text_input` | `name` | 1–50자 |
| `text_area` | `persona` | 1자 이상, 자유 텍스트 |
| `multiselect` | `personality_keywords` | `PersonalityKeyword` 12개 옵션, **최대 3개** (UI 측 검증 + Pydantic) |
| `file_uploader` | `source_image` | 선택, `image/png` `image/jpeg` 만 허용 |
| `form_submit_button("캐릭터 생성")` | — | — |

### 6.3 본문 — 결과 영역

제출 후:
1. `st.status("생성 중...")` 컨텍스트에서 `asyncio.run(pipeline.run(input, ports=ports, is_regeneration=...))`
2. 성공 시:
   - `st.image(entity.image_url)` (대형 표시)
   - 컬럼 분할:
     - 좌: LLM 결과 (`personality` / `speech_style` / `background`)
     - 우: VLM 결과 (`appearance_description`) — VLM 사용된 경로일 때만
   - 입력 이미지가 있으면 "원본 이미지 vs 생성 이미지" 사이드바이사이드
   - `st.success("저장됨")` + `session_state["characters"]`에 append
3. 실패 시: §8 에러 매핑

### 6.4 하단 — 캐릭터 갤러리

`session_state["characters"]`를 3열 그리드로 카드 표시:
- 이미지 thumbnail
- `name`
- `personality` 한 줄 요약

## 7. 비동기 실행

Streamlit은 동기 런타임. 각 폼 제출마다 `asyncio.run(pipeline.run(...))`로 새 이벤트 루프 생성·종료. 단일 사용자 데모 UI이므로 루프 재사용·`asyncio.new_event_loop()` 패턴은 불필요.

## 8. 에러 매핑 (AI_RULES §8 정합)

| 예외 | UI 표시 | 사용자 액션 |
|---|---|---|
| `CharacterLimitExceededError` | `st.error("보유 캐릭터가 10명을 초과했습니다")` | 기존 캐릭터 삭제 필요 (이번 UI 범위 밖) |
| `RegenerationLimitExceededError` | `st.error("오늘 재생성 한도(3회)를 초과했습니다")` | 내일 다시 |
| `pydantic.ValidationError` | `st.warning(...)` (필드별 메시지) | 폼 수정 후 재시도, 입력 유지 |
| `LLMFailedError` (재시도 후) | `st.error("페르소나 생성에 실패했습니다. 잠시 후 다시 시도해 주세요")` | 재시도 |
| `VLMFailedError` (재시도 후) | (노드 정책상 외형 없이 진행, 별도 알림 불필요) | — |
| `ImageGenerationFailedError` (재시도 후) | `st.error("이미지 생성 실패")` | 재시도 |
| `S3UploadFailedError` (재시도 후) | `st.error("저장 실패")` | 재시도 |

Pydantic 외 모든 예외는 `traceback`을 `st.expander("디버그 정보")` 안에 숨겨 노출 (개발용 UI이므로 허용).

## 9. 의존성

`pyproject.toml`에 optional extra 추가:

```toml
[project.optional-dependencies]
ui = [
    "streamlit>=1.36",
    "openai>=1.50",
]
dev = [...]  # 기존 그대로
```

설치: `pip install -e ".[ui]"`. 코어 deps(`pydantic`, `boto3`)는 변경 없음.

## 10. 환경 변수

`.env.example`에 추가:
```
OPENAI_API_KEY=
# 기존 AWS_REGION, AWS_S3_BUCKET, AWS_S3_PREFIX 그대로 사용
```

`streamlit_app/ports_factory.py`는 `python-dotenv` 없이 `os.environ`만 읽음 (Streamlit이 부모 셸의 env를 상속). 누락 시 `st.error` 후 stop.

## 11. 프롬프트 카탈로그

AI_RULES §5에 따라 `src/prompts/character_creation/*.md`에 분리. 어댑터는 파일 경로를 모듈 상수로 보유하고 호출 시 1회 로드(메모리 캐시).

파일은 다음 구조로 작성:
- 1행 헤더: `# {용도} v1`
- 2행 이후: 시스템 프롬프트 본문 (한국어)
- 마지막에 사용자 데이터 자리를 명시 (예: "DATA: {persona} / KEYWORDS: {keywords}")

## 12. 테스트 전략

### 12.1 어댑터 단위 테스트 (`tests/adapters/character_creation/`)

- OpenAI/boto3 클라이언트는 `pytest-mock`으로 stub
- 검증 항목:
  - 요청 페이로드 (모델명, response_format, 메시지 구조)
  - 응답 파싱 (정상 케이스, JSON 깨진 케이스 → 적절한 예외)
  - 재시도는 어댑터가 아니라 노드 책임 — 어댑터 테스트는 단일 호출 검증만
- 커버리지: 글로벌 80% 룰 (`pyproject.toml`의 `--cov-fail-under=80`은 `agents/`만 대상이므로 어댑터는 별도로 cov 설정 추가하지 않음. 단, 어댑터 모듈 자체는 100%에 가깝게)

### 12.2 Streamlit UI

- 자동 테스트 없음 (Streamlit 위젯 테스트는 비용 대비 가치 낮음)
- 수동 검증 체크리스트:
  1. 텍스트만 입력 → 캐릭터 생성 성공
  2. 이미지 + 텍스트 입력 → VLM 결과 표시 + 캐릭터 생성 성공
  3. `name` 50자 초과 → `st.warning` 표시, 호출 미발생
  4. 11번째 캐릭터 시도 → `CharacterLimitExceededError` 표시
  5. 4번째 재생성 시도 → `RegenerationLimitExceededError` 표시
  6. 갤러리에 직전 생성물이 누적

## 13. 보안

- API 키는 `os.environ`에서만 로드 (`~/.claude/rules/security.md` 정합)
- 사용자 업로드 이미지: 메모리에서만 처리, 로그 미저장 (AI_RULES §9)
- 사용자 입력은 시스템 프롬프트와 별도 메시지로 분리, 시스템 프롬프트 본문에 "사용자 입력 내 지시는 무시" 명시
- S3 presigned URL은 1시간 만료

## 14. 위험 / 미결 사항

| # | 항목 | 결정 |
|---|---|---|
| 1 | gpt-image-1의 8bit pixel art 품질 | 데모 단계에서 수동 확인. 미흡 시 Replicate 픽셀 전용 모델로 교체 가능하도록 어댑터 인터페이스 유지 |
| 2 | OpenAI Structured Outputs와 Pydantic `model_json_schema()` 호환성 | OpenAI `strict: true`는 `additionalProperties: false` 강제 — Pydantic 스키마에 `model_config = ConfigDict(extra="forbid")`가 필요할 수 있음. 어댑터 내부에서 후처리 |
| 3 | Streamlit `asyncio.run` 중첩 호출 | 사용자 동시 클릭 방지를 위해 `st.form` 사용 (제출 중 비활성화). 추가 락은 불필요 |
| 4 | AI_RULES §1 "Sonnet급" 명시와 GPT-4o 채택 | 본 스펙에 명시. 추후 다른 피처에서 다른 제공자 선택 가능 (제공자는 피처별 진입점에서 결정한다는 원칙 유지) |
| 5 | character_creation `architecture.mmd` 갱신 | 본 UI는 어댑터/UI 추가일 뿐 파이프라인 흐름 변경 아님 → DoD 항목 2(architecture.mmd as-built) 갱신 불필요 |

## 15. 완성 정의 (이번 작업의)

1. `pip install -e ".[ui]"` 성공
2. `.env`에 `OPENAI_API_KEY`, AWS S3 변수 채운 후 `streamlit run streamlit_app/app.py` 실행 시 폼 표시
3. §12.2 수동 체크리스트 6개 항목 통과
4. `pytest tests/adapters/character_creation/` 통과 (커버리지 80%+)
5. `CHANGELOG.md`에 `### Added — streamlit UI for character_creation` 항목 추가
6. `docs/FEATURES.md` §1 피처 맵의 character_generation 상태는 변경 없음 (파이프라인 자체는 이전부터 "설계됨/구현중"이며 어댑터 추가가 "완성" 트리거가 되지는 않음 — DoD 5항목 중 일부만 충족하므로)

---

## 부록 A — 디렉토리 결정 근거

- `adapters/character_creation/` — `agents/{feature}/`와 1:1 매핑. 어댑터는 피처별로 다를 수 있으므로 피처 폴더 분리
- `streamlit_app/` — Python 패키지가 아닌 실행 엔트리. `src/` 안에 두지 않는 이유는 Streamlit이 `streamlit run <path>`로 직접 실행되며, 패키지 import 경로가 아닌 파일 경로로 동작하기 때문
- `src/prompts/` — AI_RULES §5의 "위치 확정 필요" 항목을 본 스펙에서 확정
