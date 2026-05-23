# 캐릭터 생성 에이전트 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/features/character_generation/CLAUDE.md` 의 8단계 파이프라인(Validation → Router → LLM·VLM·이미지 업로드 → 이미지 생성 → 빌드 → 저장)을 `agents/character_creation/` 아래 TDD 로 구현한다. 외부 의존(LLM/VLM/Image Generator/S3/DB)은 모두 Protocol 로 추상화하여 테스트 시 페이크로 치환한다.

**Architecture:** 헥사고날(포트·어댑터). `pipeline.py` 가 오케스트레이션, `nodes/*` 가 단위 단계, `protocols.py` 가 외부 의존 인터페이스, `repository.py` 가 DB 어댑터. **에이전트는 순수 함수에 가깝게(`pipeline.run(input, ports) -> CharacterEntity`)**, 카운터 증가·트랜잭션 outbox 등 부수효과는 호출자가 주입한 포트를 통해 위임 (`docs/FEATURES.md` §3.2 표준). LLM·VLM 는 `asyncio.gather` 로 병렬, VLM 실패는 외형 정보 없이 진행하는 "degrade-on-fail" 정책.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest + pytest-asyncio + pytest-cov + pytest-mock, asyncio. 외부 SDK(boto3/aioboto3, anthropic, SQLAlchemy 등)는 본 계획에서 직접 사용하지 않고 Protocol 포트만 정의 — 실제 어댑터 구현은 후속 PR.

**참고 문서:**
- 피처 설계서: `docs/features/character_generation/CLAUDE.md`
- 아키텍처 다이어그램: `docs/features/character_generation/architecture.mmd`
- 공통 AI 규칙: `docs/AI_RULES.md` (§3 재시도 표, §2 구조화 출력, §9 보안)
- 데이터 모델: `docs/DATA_MODEL.md` §2.1 `characters`, §6.3 `img_gen_logs`
- 공통 패턴·DoD: `docs/FEATURES.md` §3, §4

---

## 0. 사전 결정 — 피처 문서 §8 "미결 사항" 처리

DoD 4번 ("미결 사항 해소") 를 본 PR 내에서 충족시키기 위해 다음과 같이 결정한다. 코드 결정사항은 `agents/character_creation/decisions.md` 에 기록하고, 피처 문서 §8 은 Task 14 에서 "결정됨" 으로 갱신한다.

| # | 항목 | 결정 |
|---|---|---|
| 1 | 이미지 생성 모델 선택 | 단일 `ImageGenerator` Protocol 만 정의. text-only / image-input 분기는 어댑터 내부에서 처리하고 파이프라인은 알지 못한다. |
| 2 | "재생성" 단위 | **이미지 생성 호출 1회 = 재생성 1회**. `nodes/image_generator.py` 진입 시 호출자 측 카운터(`img_gen_logs.gen_cnt`)를 증가시키는 콜백을 받는다 (에이전트 외부 책임이지만, 호출 시점은 에이전트가 통지). |
| 3 | VLM 실패 정책 | **degrade-on-fail.** 재시도 2회 모두 실패 시 `VLMResult` 없이 LLM 결과 + 페르소나 텍스트만으로 이미지 생성 진행. 결정 근거: VLM 은 정체성 강화용이지 필수 입력이 아님 (architecture.mmd 도 VLM 을 enhancement edge 로 표기). |
| 4 | 병렬 처리 범위 | `asyncio.gather(llm_task, vlm_task)` 로 LLM·VLM 병렬 실행. 이미지 업로드(S3) 는 VLM 과 같은 이미지 입력 분기 내에서 순차 (VLM 입력 전 byte 를 읽으므로 의미적 직렬). |
| 5 | 이미지 생성 프롬프트 조립 책임 | `ImageGenerator.generate(*, llm_result, vlm_result, fallback_persona, user_id)` 시그니처. 프롬프트 조립은 어댑터 내부. 파이프라인은 구조화 입력만 전달. |

---

## 1. File Structure

| 파일 | 책임 | 작업 종류 |
|---|---|---|
| `pyproject.toml` | 패키지 메타데이터, 의존성, pytest/coverage 설정 | 신규 |
| `agents/__init__.py` | 빈 패키지 마커 | 신규 |
| `agents/character_creation/__init__.py` | 패키지 export (`run`, 주요 스키마) | 신규 |
| `agents/character_creation/schemas.py` | Pydantic 모델: 입력/중간/출력 | 신규 |
| `agents/character_creation/exceptions.py` | 도메인 예외 4종 | 신규 |
| `agents/character_creation/protocols.py` | 외부 의존 포트 (LLM/VLM/Image/S3/Repository) | 신규 |
| `agents/character_creation/validation.py` | C1~C4 검사 | 신규 |
| `agents/character_creation/router.py` | `source_image` 유무로 실행 경로 결정 | 신규 |
| `agents/character_creation/nodes/__init__.py` | 빈 마커 | 신규 |
| `agents/character_creation/nodes/llm_persona.py` | §5.3 LLM (재시도 2회) | 신규 |
| `agents/character_creation/nodes/image_upload.py` | §5.4 S3 업로드 (재시도 3회) | 신규 |
| `agents/character_creation/nodes/vlm_analyzer.py` | §5.5 VLM (재시도 2회, degrade-on-fail) | 신규 |
| `agents/character_creation/nodes/image_generator.py` | §5.6 ImageGenerator 호출 (재시도 1회) | 신규 |
| `agents/character_creation/nodes/builder.py` | §5.7 도메인 엔티티 조립 | 신규 |
| `agents/character_creation/repository.py` | §5.8 인메모리 fake (실제 MySQL 어댑터는 후속 PR) | 신규 |
| `agents/character_creation/pipeline.py` | 오케스트레이션 entry point | 신규 |
| `agents/character_creation/decisions.md` | 본 PR 의 §0 결정사항 영구 기록 | 신규 |
| `tests/__init__.py` | 빈 마커 | 신규 |
| `tests/conftest.py` | 공용 fixture (페이크 포트, 샘플 입력) | 신규 |
| `tests/agents/__init__.py` | 빈 마커 | 신규 |
| `tests/agents/character_creation/__init__.py` | 빈 마커 | 신규 |
| `tests/agents/character_creation/fakes.py` | LLM/VLM/Image/S3/Repository 인메모리 페이크 + 실패 시뮬레이션 | 신규 |
| `tests/agents/character_creation/test_*.py` | 노드별/파이프라인 단위·통합 테스트 | 신규 |
| `docs/features/character_generation/architecture.mmd` | as-built 갱신 (Task 14) | 수정 |
| `docs/features/character_generation/CLAUDE.md` | §8 미결 사항 → "결정됨" 으로 갱신 (Task 14) | 수정 |
| `CHANGELOG.md` | `[Unreleased]` 에 본 작업 항목 추가 (Task 14) | 수정 |
| `docs/TODO.md` | `## 완료` 에 1줄 기록 (Task 14) | 수정 |

### 실행 순서 의존성

```
Task 1  (프로젝트 셋업: pyproject.toml, conftest.py)
   │
   ├─→ Task 2  (schemas.py)
   ├─→ Task 3  (exceptions.py)
   └─→ Task 4  (protocols.py + fakes.py)
                    │
                    ↓
        Task 5 (validation) ─┐
        Task 6 (router) ─────┤
        Task 7 (llm_persona) ┤── 단위 노드, 서로 독립
        Task 8 (image_upload)┤
        Task 9 (vlm_analyzer)┤
        Task 10 (image_gen)  ┤
        Task 11 (builder) ───┤
        Task 12 (repository)─┘
                    │
                    ↓
        Task 13 (pipeline.py 오케스트레이션)
                    │
                    ↓
        Task 14 (DoD 마무리: mmd / CLAUDE.md §8 / CHANGELOG / TODO)
```

---

## Task 1: 프로젝트 셋업 (pyproject.toml + conftest.py)

**Files:**
- Create: `pyproject.toml`
- Create: `agents/__init__.py`
- Create: `agents/character_creation/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/agents/__init__.py`
- Create: `tests/agents/character_creation/__init__.py`

- [ ] **Step 1.1: `pyproject.toml` 작성**

```toml
[project]
name = "mongle-village"
version = "0.1.0"
description = "Monggeul Village — character / todo / quest / feed AI agents"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6,<3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "pytest-mock>=3.12",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-ra --strict-markers --cov=agents --cov-report=term-missing --cov-fail-under=80"

[tool.coverage.run]
branch = true
source = ["agents"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "raise NotImplementedError",
    "if TYPE_CHECKING:",
]
```

- [ ] **Step 1.2: 빈 마커 파일 5개 생성**

Create empty files: `agents/__init__.py`, `agents/character_creation/__init__.py`, `tests/__init__.py`, `tests/agents/__init__.py`, `tests/agents/character_creation/__init__.py`

- [ ] **Step 1.3: `tests/conftest.py` 작성 (공용 fixture)**

```python
from __future__ import annotations

import pytest


@pytest.fixture
def sample_user_id() -> str:
    return "user-0001"


@pytest.fixture
def sample_persona_text() -> str:
    return "낮잠을 좋아하지만 사용자에게 다정한 곰돌이."


@pytest.fixture
def sample_keywords() -> list[str]:
    return ["다정한", "온화한"]


@pytest.fixture
def sample_image_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    )
```

- [ ] **Step 1.4: 인프라 검증**

Run:
```bash
python -m pip install -e ".[dev]"
```
Expected: 설치 성공, exit code 0.

Run:
```bash
pytest --collect-only --no-cov
```
Expected: import 에러 없이 0 tests collected.

---

## Task 2: `agents/character_creation/schemas.py` — Pydantic 모델

**Files:**
- Create: `agents/character_creation/schemas.py`
- Create: `tests/agents/character_creation/test_schemas.py`

- [ ] **Step 2.1: 실패 테스트 작성**

`tests/agents/character_creation/test_schemas.py`:

```python
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
    PersonalityKeyword,
    VLMResult,
)


def test_personality_keyword_enum_has_12_values() -> None:
    assert len(PersonalityKeyword) == 12
    assert PersonalityKeyword("다정한") is PersonalityKeyword.AFFECTIONATE


def test_input_requires_persona_and_name(sample_user_id: str) -> None:
    with pytest.raises(ValidationError):
        CharacterCreationInput(user_id=sample_user_id)  # type: ignore[call-arg]


def test_input_rejects_more_than_three_keywords(sample_user_id: str) -> None:
    with pytest.raises(ValidationError):
        CharacterCreationInput(
            user_id=sample_user_id,
            name="몽글이",
            persona="설명",
            personality_keywords=[
                PersonalityKeyword.AFFECTIONATE,
                PersonalityKeyword.CALM,
                PersonalityKeyword.BRAVE,
                PersonalityKeyword.CHEERFUL,
            ],
        )


def test_llm_persona_result_all_fields_required() -> None:
    with pytest.raises(ValidationError):
        LLMPersonaResult(personality="x", speech_style="y")  # type: ignore[call-arg]


def test_vlm_result_holds_appearance_description() -> None:
    result = VLMResult(appearance_description="둥근 갈색 곰, 빨간 리본")
    assert "곰" in result.appearance_description


def test_character_entity_serializes_round_trip(sample_user_id: str) -> None:
    entity = CharacterEntity(
        character_id=uuid4(),
        user_id=sample_user_id,
        name="몽글이",
        persona="...",
        personality="다정함",
        speech_style="존댓말",
        background="숲에서 옴",
        image_url="https://s3/characters/x.png",
        source_image_url=None,
        created_at=datetime(2026, 5, 22, 12, 0, 0),
    )
    dumped = entity.model_dump()
    assert dumped["source_image_url"] is None
    assert dumped["name"] == "몽글이"
```

- [ ] **Step 2.2: 테스트 실패 확인**

Run:
```bash
pytest tests/agents/character_creation/test_schemas.py --no-cov -v
```
Expected: `ModuleNotFoundError: agents.character_creation.schemas`.

- [ ] **Step 2.3: `schemas.py` 구현**

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PersonalityKeyword(str, Enum):
    ADVENTUROUS = "모험적인"
    CALM = "차분한"
    CURIOUS = "호기심많은"
    AFFECTIONATE = "다정한"
    PLAYFUL = "장난스러운"
    DILIGENT = "부지런한"
    STRONG = "강력한"
    DREAMY = "몽환적인"
    ANGRY = "분노가 많은"
    BRAVE = "용감한"
    GENTLE = "온화한"
    CHEERFUL = "명랑한"


class SourceImage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    filename: str
    content_type: str
    data: bytes


class CharacterCreationInput(BaseModel):
    user_id: str
    name: Annotated[str, Field(min_length=1, max_length=50)]
    persona: Annotated[str, Field(min_length=1)]
    personality_keywords: Annotated[
        list[PersonalityKeyword],
        Field(default_factory=list, max_length=3),
    ]
    source_image: SourceImage | None = None


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
```

- [ ] **Step 2.4: 테스트 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_schemas.py --no-cov -v
```
Expected: 6 passed.

---

## Task 3: `agents/character_creation/exceptions.py` — 도메인 예외

**Files:**
- Create: `agents/character_creation/exceptions.py`
- Create: `tests/agents/character_creation/test_exceptions.py`

- [ ] **Step 3.1: 실패 테스트 작성**

```python
from __future__ import annotations

import pytest

from agents.character_creation.exceptions import (
    CharacterCreationError,
    ExternalServiceError,
    ImageGenerationFailedError,
    LLMFailedError,
    S3UploadFailedError,
    ValidationFailedError,
)


def test_validation_error_is_subclass_of_creation_error() -> None:
    err = ValidationFailedError(code="C1", message="보유 캐릭터 ≥ 10")
    assert isinstance(err, CharacterCreationError)
    assert err.code == "C1"
    assert "C1" in str(err)


@pytest.mark.parametrize(
    "exc_cls",
    [LLMFailedError, S3UploadFailedError, ImageGenerationFailedError],
)
def test_external_errors_subclass_external_service_error(exc_cls: type) -> None:
    err = exc_cls("upstream timeout")
    assert isinstance(err, ExternalServiceError)
    assert isinstance(err, CharacterCreationError)
```

- [ ] **Step 3.2: 실패 확인**

Run:
```bash
pytest tests/agents/character_creation/test_exceptions.py --no-cov -v
```
Expected: ImportError.

- [ ] **Step 3.3: `exceptions.py` 구현**

```python
from __future__ import annotations


class CharacterCreationError(Exception):
    pass


class ValidationFailedError(CharacterCreationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class ExternalServiceError(CharacterCreationError):
    pass


class LLMFailedError(ExternalServiceError):
    pass


class VLMFailedError(ExternalServiceError):
    pass


class S3UploadFailedError(ExternalServiceError):
    pass


class ImageGenerationFailedError(ExternalServiceError):
    pass
```

- [ ] **Step 3.4: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_exceptions.py --no-cov -v
```
Expected: 4 passed.

---

## Task 4: `protocols.py` + 테스트 페이크

**Files:**
- Create: `agents/character_creation/protocols.py`
- Create: `tests/agents/character_creation/fakes.py`
- Create: `tests/agents/character_creation/test_fakes.py`

- [ ] **Step 4.1: `protocols.py` 작성**

```python
from __future__ import annotations

from typing import Protocol

from agents.character_creation.schemas import (
    CharacterEntity,
    LLMPersonaResult,
    PersonalityKeyword,
    SourceImage,
    VLMResult,
)


class LLMPort(Protocol):
    async def generate_persona(
        self,
        *,
        persona: str,
        keywords: list[PersonalityKeyword],
    ) -> LLMPersonaResult: ...


class VLMPort(Protocol):
    async def extract_appearance(self, image: SourceImage) -> VLMResult: ...


class S3Port(Protocol):
    async def put_object(self, *, key: str, body: bytes, content_type: str) -> str: ...


class ImageGeneratorPort(Protocol):
    async def generate(
        self,
        *,
        user_id: str,
        llm_result: LLMPersonaResult,
        vlm_result: VLMResult | None,
        fallback_persona: str | None,
    ) -> bytes: ...


class RegenerationCounterPort(Protocol):
    async def increment(self, user_id: str) -> int: ...


class CharacterRepositoryPort(Protocol):
    async def count_active(self, user_id: str) -> int: ...
    async def today_regen_count(self, user_id: str) -> int: ...
    async def save(self, entity: CharacterEntity) -> None: ...
    async def delete_image_keys(self, keys: list[str]) -> None: ...
```

- [ ] **Step 4.2: `fakes.py` 작성**

```python
from __future__ import annotations

from dataclasses import dataclass, field

from agents.character_creation.exceptions import (
    ImageGenerationFailedError,
    LLMFailedError,
    S3UploadFailedError,
    VLMFailedError,
)
from agents.character_creation.schemas import (
    CharacterEntity,
    LLMPersonaResult,
    PersonalityKeyword,
    SourceImage,
    VLMResult,
)


@dataclass
class FakeLLM:
    fail_times: int = 0
    calls: int = 0

    async def generate_persona(
        self,
        *,
        persona: str,
        keywords: list[PersonalityKeyword],
    ) -> LLMPersonaResult:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMFailedError("simulated LLM failure")
        return LLMPersonaResult(
            personality=f"성격:{persona[:5]}",
            speech_style="존댓말",
            background="조용한 숲에서 옴",
        )


@dataclass
class FakeVLM:
    fail_times: int = 0
    calls: int = 0

    async def extract_appearance(self, image: SourceImage) -> VLMResult:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise VLMFailedError("simulated VLM failure")
        return VLMResult(appearance_description="둥근 갈색 곰")


@dataclass
class FakeS3:
    fail_times: int = 0
    stored: dict[str, bytes] = field(default_factory=dict)
    calls: int = 0

    async def put_object(
        self, *, key: str, body: bytes, content_type: str
    ) -> str:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise S3UploadFailedError("simulated S3 failure")
        self.stored[key] = body
        return f"https://fake-s3.local/{key}"


@dataclass
class FakeImageGenerator:
    fail_times: int = 0
    calls: int = 0
    last_inputs: dict = field(default_factory=dict)

    async def generate(
        self,
        *,
        user_id: str,
        llm_result: LLMPersonaResult,
        vlm_result: VLMResult | None,
        fallback_persona: str | None,
    ) -> bytes:
        self.calls += 1
        self.last_inputs = {
            "user_id": user_id,
            "llm_result": llm_result,
            "vlm_result": vlm_result,
            "fallback_persona": fallback_persona,
        }
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ImageGenerationFailedError("simulated img gen failure")
        return b"GENERATED_PNG_BYTES"


@dataclass
class FakeCounter:
    today: int = 0

    async def increment(self, user_id: str) -> int:
        self.today += 1
        return self.today


@dataclass
class FakeRepository:
    active_count: int = 0
    regen_count_today: int = 0
    saved: list[CharacterEntity] = field(default_factory=list)
    deleted_keys: list[str] = field(default_factory=list)
    save_should_fail: bool = False

    async def count_active(self, user_id: str) -> int:
        return self.active_count

    async def today_regen_count(self, user_id: str) -> int:
        return self.regen_count_today

    async def save(self, entity: CharacterEntity) -> None:
        if self.save_should_fail:
            raise RuntimeError("simulated DB failure")
        self.saved.append(entity)

    async def delete_image_keys(self, keys: list[str]) -> None:
        self.deleted_keys.extend(keys)
```

- [ ] **Step 4.3: `test_fakes.py` 작성**

```python
from __future__ import annotations

import pytest

from agents.character_creation.exceptions import LLMFailedError, S3UploadFailedError
from tests.agents.character_creation.fakes import FakeLLM, FakeS3


async def test_fake_llm_returns_struct_after_failures() -> None:
    llm = FakeLLM(fail_times=2)
    with pytest.raises(LLMFailedError):
        await llm.generate_persona(persona="x", keywords=[])
    with pytest.raises(LLMFailedError):
        await llm.generate_persona(persona="x", keywords=[])
    result = await llm.generate_persona(persona="hello", keywords=[])
    assert result.personality.startswith("성격:")
    assert llm.calls == 3


async def test_fake_s3_stores_bytes_under_key() -> None:
    s3 = FakeS3()
    url = await s3.put_object(key="k", body=b"abc", content_type="image/png")
    assert url.endswith("/k")
    assert s3.stored["k"] == b"abc"


async def test_fake_s3_simulates_failure() -> None:
    s3 = FakeS3(fail_times=1)
    with pytest.raises(S3UploadFailedError):
        await s3.put_object(key="k", body=b"abc", content_type="image/png")
    url = await s3.put_object(key="k", body=b"abc", content_type="image/png")
    assert url
```

- [ ] **Step 4.4: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_fakes.py --no-cov -v
```
Expected: 3 passed.

---

## Task 5: `validation.py` — C1~C4 검사

**Files:**
- Create: `agents/character_creation/validation.py`
- Create: `tests/agents/character_creation/test_validation.py`

- [ ] **Step 5.1: 실패 테스트 작성**

```python
from __future__ import annotations

import pytest

from agents.character_creation.exceptions import ValidationFailedError
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from agents.character_creation.validation import check
from tests.agents.character_creation.fakes import FakeRepository


def _input(**overrides) -> CharacterCreationInput:
    defaults = {
        "user_id": "u",
        "name": "몽글이",
        "persona": "다정한 곰",
        "personality_keywords": [],
        "source_image": None,
    }
    defaults.update(overrides)
    return CharacterCreationInput(**defaults)


async def test_passes_when_within_all_limits() -> None:
    repo = FakeRepository(active_count=0, regen_count_today=0)
    await check(_input(), repo=repo, is_regeneration=False)


async def test_rejects_when_active_characters_at_limit() -> None:
    repo = FakeRepository(active_count=10)
    with pytest.raises(ValidationFailedError) as exc:
        await check(_input(), repo=repo, is_regeneration=False)
    assert exc.value.code == "C1"


async def test_rejects_when_regen_count_exceeded() -> None:
    repo = FakeRepository(active_count=1, regen_count_today=3)
    with pytest.raises(ValidationFailedError) as exc:
        await check(_input(), repo=repo, is_regeneration=True)
    assert exc.value.code == "C2"


async def test_does_not_check_regen_when_not_regeneration() -> None:
    repo = FakeRepository(active_count=1, regen_count_today=99)
    await check(_input(), repo=repo, is_regeneration=False)


@pytest.mark.parametrize("content_type", ["image/gif", "application/pdf", "text/plain"])
async def test_rejects_disallowed_mime(content_type: str) -> None:
    repo = FakeRepository()
    src = SourceImage(filename="x", content_type=content_type, data=b"\x00")
    with pytest.raises(ValidationFailedError) as exc:
        await check(_input(source_image=src), repo=repo, is_regeneration=False)
    assert exc.value.code == "C3"


async def test_rejects_image_larger_than_5mb() -> None:
    repo = FakeRepository()
    src = SourceImage(
        filename="x.png",
        content_type="image/png",
        data=b"\x00" * (5 * 1024 * 1024 + 1),
    )
    with pytest.raises(ValidationFailedError) as exc:
        await check(_input(source_image=src), repo=repo, is_regeneration=False)
    assert exc.value.code == "C4"


async def test_accepts_image_at_5mb_boundary() -> None:
    repo = FakeRepository()
    src = SourceImage(
        filename="x.png",
        content_type="image/png",
        data=b"\x00" * (5 * 1024 * 1024),
    )
    await check(_input(source_image=src), repo=repo, is_regeneration=False)
```

- [ ] **Step 5.2: 실패 확인 → 구현**

`validation.py`:

```python
from __future__ import annotations

from agents.character_creation.exceptions import ValidationFailedError
from agents.character_creation.protocols import CharacterRepositoryPort
from agents.character_creation.schemas import CharacterCreationInput

ALLOWED_MIME = {"image/jpeg", "image/jpg", "image/png"}
MAX_BYTES = 5 * 1024 * 1024
MAX_ACTIVE_CHARACTERS = 10
MAX_DAILY_REGEN = 3


async def check(
    input: CharacterCreationInput,
    *,
    repo: CharacterRepositoryPort,
    is_regeneration: bool,
) -> None:
    if await repo.count_active(input.user_id) >= MAX_ACTIVE_CHARACTERS:
        raise ValidationFailedError(
            code="C1",
            message=f"보유 캐릭터가 {MAX_ACTIVE_CHARACTERS}개를 초과했습니다.",
        )

    if is_regeneration:
        used = await repo.today_regen_count(input.user_id)
        if used >= MAX_DAILY_REGEN:
            raise ValidationFailedError(
                code="C2",
                message=f"오늘 재생성 횟수가 {MAX_DAILY_REGEN}회를 초과했습니다.",
            )

    if input.source_image is not None:
        if input.source_image.content_type not in ALLOWED_MIME:
            raise ValidationFailedError(
                code="C3",
                message=f"허용되지 않는 형식: {input.source_image.content_type}",
            )
        if len(input.source_image.data) > MAX_BYTES:
            raise ValidationFailedError(
                code="C4",
                message="이미지가 5MB를 초과합니다.",
            )
```

- [ ] **Step 5.3: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_validation.py --no-cov -v
```
Expected: 9 passed.

---

## Task 6: `router.py` — 입력 분기

**Files:**
- Create: `agents/character_creation/router.py`
- Create: `tests/agents/character_creation/test_router.py`

- [ ] **Step 6.1: 실패 테스트 작성**

```python
from __future__ import annotations

from agents.character_creation.router import RouteDecision, decide
from agents.character_creation.schemas import CharacterCreationInput, SourceImage


def test_text_only_input() -> None:
    inp = CharacterCreationInput(user_id="u", name="n", persona="p")
    assert decide(inp) == RouteDecision.TEXT_ONLY


def test_image_plus_text_input() -> None:
    inp = CharacterCreationInput(
        user_id="u",
        name="n",
        persona="p",
        source_image=SourceImage(filename="x.png", content_type="image/png", data=b"\x00"),
    )
    assert decide(inp) == RouteDecision.IMAGE_AND_TEXT
```

- [ ] **Step 6.2: 구현**

`router.py`:

```python
from __future__ import annotations

from enum import Enum

from agents.character_creation.schemas import CharacterCreationInput


class RouteDecision(str, Enum):
    TEXT_ONLY = "text_only"
    IMAGE_AND_TEXT = "image_and_text"


def decide(input: CharacterCreationInput) -> RouteDecision:
    return (
        RouteDecision.IMAGE_AND_TEXT
        if input.source_image is not None
        else RouteDecision.TEXT_ONLY
    )
```

- [ ] **Step 6.3: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_router.py --no-cov -v
```
Expected: 2 passed.

---

## Task 7: `nodes/llm_persona.py` — LLM 호출 + 재시도 2회

**Files:**
- Create: `agents/character_creation/nodes/__init__.py` (빈 파일)
- Create: `agents/character_creation/nodes/llm_persona.py`
- Create: `tests/agents/character_creation/test_llm_persona.py`

- [ ] **Step 7.1: 실패 테스트 작성**

```python
from __future__ import annotations

import pytest

from agents.character_creation.exceptions import LLMFailedError
from agents.character_creation.nodes.llm_persona import generate
from tests.agents.character_creation.fakes import FakeLLM


async def test_returns_result_on_first_attempt() -> None:
    llm = FakeLLM()
    result = await generate(llm, persona="다정한 곰", keywords=[])
    assert result.personality
    assert result.speech_style
    assert result.background
    assert llm.calls == 1


async def test_retries_up_to_two_times() -> None:
    llm = FakeLLM(fail_times=2)
    result = await generate(llm, persona="다정한 곰", keywords=[])
    assert result.personality
    assert llm.calls == 3


async def test_gives_up_after_two_retries() -> None:
    llm = FakeLLM(fail_times=3)
    with pytest.raises(LLMFailedError):
        await generate(llm, persona="다정한 곰", keywords=[])
    assert llm.calls == 3
```

- [ ] **Step 7.2: 구현**

`nodes/__init__.py`: 빈 파일.

`nodes/llm_persona.py`:

```python
from __future__ import annotations

from agents.character_creation.exceptions import LLMFailedError
from agents.character_creation.protocols import LLMPort
from agents.character_creation.schemas import LLMPersonaResult, PersonalityKeyword

MAX_RETRIES = 2


async def generate(
    llm: LLMPort,
    *,
    persona: str,
    keywords: list[PersonalityKeyword],
) -> LLMPersonaResult:
    last_error: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            return await llm.generate_persona(persona=persona, keywords=keywords)
        except LLMFailedError as err:
            last_error = err
    assert last_error is not None
    raise last_error
```

- [ ] **Step 7.3: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_llm_persona.py --no-cov -v
```
Expected: 3 passed.

---

## Task 8: `nodes/image_upload.py` — S3 업로드 + 재시도 3회

**Files:**
- Create: `agents/character_creation/nodes/image_upload.py`
- Create: `tests/agents/character_creation/test_image_upload.py`

- [ ] **Step 8.1: 실패 테스트 작성**

```python
from __future__ import annotations

import pytest

from agents.character_creation.exceptions import S3UploadFailedError
from agents.character_creation.nodes.image_upload import store_source
from agents.character_creation.schemas import SourceImage
from tests.agents.character_creation.fakes import FakeS3


def _src(content_type: str = "image/png", data: bytes = b"\x89PNG\r\n") -> SourceImage:
    return SourceImage(filename="upload.png", content_type=content_type, data=data)


async def test_uploads_and_returns_url() -> None:
    s3 = FakeS3()
    url, key = await store_source(s3, image=_src(), user_id="u1")
    assert url.endswith(key)
    assert key.startswith("sources/u1/")
    assert key.endswith(".png")


async def test_key_uses_correct_extension_for_jpeg() -> None:
    s3 = FakeS3()
    _, key = await store_source(s3, image=_src(content_type="image/jpeg"), user_id="u1")
    assert key.endswith(".jpg")


async def test_retries_up_to_three_times() -> None:
    s3 = FakeS3(fail_times=3)
    url, _ = await store_source(s3, image=_src(), user_id="u1")
    assert url
    assert s3.calls == 4


async def test_gives_up_after_three_retries() -> None:
    s3 = FakeS3(fail_times=4)
    with pytest.raises(S3UploadFailedError):
        await store_source(s3, image=_src(), user_id="u1")
    assert s3.calls == 4
```

- [ ] **Step 8.2: 구현**

`nodes/image_upload.py`:

```python
from __future__ import annotations

from uuid import uuid4

from agents.character_creation.exceptions import S3UploadFailedError
from agents.character_creation.protocols import S3Port
from agents.character_creation.schemas import SourceImage

MAX_RETRIES = 3

_EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
}


def _key_for(user_id: str, content_type: str, prefix: str) -> str:
    ext = _EXT_BY_MIME.get(content_type, "bin")
    return f"{prefix}/{user_id}/{uuid4()}.{ext}"


async def _put_with_retry(
    s3: S3Port, *, key: str, body: bytes, content_type: str
) -> str:
    last_error: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            return await s3.put_object(key=key, body=body, content_type=content_type)
        except S3UploadFailedError as err:
            last_error = err
    assert last_error is not None
    raise last_error


async def store_source(
    s3: S3Port, *, image: SourceImage, user_id: str
) -> tuple[str, str]:
    key = _key_for(user_id, image.content_type, prefix="sources")
    url = await _put_with_retry(s3, key=key, body=image.data, content_type=image.content_type)
    return url, key


async def store_generated(
    s3: S3Port, *, body: bytes, user_id: str
) -> tuple[str, str]:
    key = _key_for(user_id, "image/png", prefix="characters")
    url = await _put_with_retry(s3, key=key, body=body, content_type="image/png")
    return url, key
```

- [ ] **Step 8.3: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_image_upload.py --no-cov -v
```
Expected: 4 passed.

---

## Task 9: `nodes/vlm_analyzer.py` — VLM + degrade-on-fail

**Files:**
- Create: `agents/character_creation/nodes/vlm_analyzer.py`
- Create: `tests/agents/character_creation/test_vlm_analyzer.py`

- [ ] **Step 9.1: 실패 테스트 작성**

```python
from __future__ import annotations

from agents.character_creation.nodes.vlm_analyzer import extract
from agents.character_creation.schemas import SourceImage
from tests.agents.character_creation.fakes import FakeVLM


def _src() -> SourceImage:
    return SourceImage(filename="x.png", content_type="image/png", data=b"\x00")


async def test_returns_result_on_success() -> None:
    vlm = FakeVLM()
    result = await extract(vlm, image=_src())
    assert result is not None
    assert "곰" in result.appearance_description
    assert vlm.calls == 1


async def test_retries_up_to_two_times() -> None:
    vlm = FakeVLM(fail_times=2)
    result = await extract(vlm, image=_src())
    assert result is not None
    assert vlm.calls == 3


async def test_returns_none_when_all_retries_fail() -> None:
    vlm = FakeVLM(fail_times=3)
    result = await extract(vlm, image=_src())
    assert result is None
    assert vlm.calls == 3
```

- [ ] **Step 9.2: 구현**

`nodes/vlm_analyzer.py`:

```python
from __future__ import annotations

from agents.character_creation.exceptions import VLMFailedError
from agents.character_creation.protocols import VLMPort
from agents.character_creation.schemas import SourceImage, VLMResult

MAX_RETRIES = 2


async def extract(vlm: VLMPort, *, image: SourceImage) -> VLMResult | None:
    for _ in range(MAX_RETRIES + 1):
        try:
            return await vlm.extract_appearance(image)
        except VLMFailedError:
            continue
    return None
```

- [ ] **Step 9.3: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_vlm_analyzer.py --no-cov -v
```
Expected: 3 passed.

---

## Task 10: `nodes/image_generator.py` — 이미지 생성 + 카운터 통지

**Files:**
- Create: `agents/character_creation/nodes/image_generator.py`
- Create: `tests/agents/character_creation/test_image_generator.py`

- [ ] **Step 10.1: 실패 테스트 작성**

```python
from __future__ import annotations

import pytest

from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.nodes.image_generator import generate_bytes
from agents.character_creation.schemas import LLMPersonaResult, VLMResult
from tests.agents.character_creation.fakes import FakeCounter, FakeImageGenerator


def _llm() -> LLMPersonaResult:
    return LLMPersonaResult(personality="다정함", speech_style="존댓말", background="숲")


async def test_uses_vlm_result_when_present() -> None:
    gen = FakeImageGenerator()
    counter = FakeCounter()
    result = await generate_bytes(
        gen,
        counter=counter,
        user_id="u1",
        llm_result=_llm(),
        vlm_result=VLMResult(appearance_description="둥근 곰"),
        fallback_persona=None,
    )
    assert result == b"GENERATED_PNG_BYTES"
    assert gen.last_inputs["vlm_result"] is not None
    assert gen.last_inputs["fallback_persona"] is None
    assert counter.today == 1


async def test_uses_fallback_persona_when_vlm_absent() -> None:
    gen = FakeImageGenerator()
    counter = FakeCounter()
    await generate_bytes(
        gen,
        counter=counter,
        user_id="u1",
        llm_result=_llm(),
        vlm_result=None,
        fallback_persona="다정한 곰돌이",
    )
    assert gen.last_inputs["vlm_result"] is None
    assert gen.last_inputs["fallback_persona"] == "다정한 곰돌이"


async def test_retries_once_on_failure() -> None:
    gen = FakeImageGenerator(fail_times=1)
    counter = FakeCounter()
    await generate_bytes(
        gen,
        counter=counter,
        user_id="u1",
        llm_result=_llm(),
        vlm_result=None,
        fallback_persona="x",
    )
    assert gen.calls == 2
    assert counter.today == 1


async def test_gives_up_after_one_retry() -> None:
    gen = FakeImageGenerator(fail_times=2)
    counter = FakeCounter()
    with pytest.raises(ImageGenerationFailedError):
        await generate_bytes(
            gen,
            counter=counter,
            user_id="u1",
            llm_result=_llm(),
            vlm_result=None,
            fallback_persona="x",
        )
    assert gen.calls == 2
```

- [ ] **Step 10.2: 구현**

`nodes/image_generator.py`:

```python
from __future__ import annotations

from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.protocols import ImageGeneratorPort, RegenerationCounterPort
from agents.character_creation.schemas import LLMPersonaResult, VLMResult

MAX_RETRIES = 1


async def generate_bytes(
    image_generator: ImageGeneratorPort,
    *,
    counter: RegenerationCounterPort,
    user_id: str,
    llm_result: LLMPersonaResult,
    vlm_result: VLMResult | None,
    fallback_persona: str | None,
) -> bytes:
    await counter.increment(user_id)

    last_error: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            return await image_generator.generate(
                user_id=user_id,
                llm_result=llm_result,
                vlm_result=vlm_result,
                fallback_persona=fallback_persona,
            )
        except ImageGenerationFailedError as err:
            last_error = err
    assert last_error is not None
    raise last_error
```

- [ ] **Step 10.3: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_image_generator.py --no-cov -v
```
Expected: 4 passed.

---

## Task 11: `nodes/builder.py` — 엔티티 조립

**Files:**
- Create: `agents/character_creation/nodes/builder.py`
- Create: `tests/agents/character_creation/test_builder.py`

- [ ] **Step 11.1: 실패 테스트 작성**

```python
from __future__ import annotations

from datetime import datetime

from agents.character_creation.nodes.builder import build
from agents.character_creation.schemas import (
    CharacterCreationInput,
    LLMPersonaResult,
    VLMResult,
)


def _input(**kw) -> CharacterCreationInput:
    return CharacterCreationInput(
        user_id="u1",
        name="몽글이",
        persona="다정한 곰",
        **kw,
    )


def _llm() -> LLMPersonaResult:
    return LLMPersonaResult(
        personality="다정한 성격",
        speech_style="존댓말",
        background="숲에서 옴",
    )


def test_builds_entity_with_all_required_fields() -> None:
    fixed_now = datetime(2026, 5, 22, 9, 0, 0)
    entity = build(
        input=_input(),
        llm_result=_llm(),
        vlm_result=VLMResult(appearance_description="둥근 곰"),
        generated_image_url="https://s3/characters/u1/x.png",
        source_image_url="https://s3/sources/u1/y.png",
        now=fixed_now,
    )
    assert entity.user_id == "u1"
    assert entity.name == "몽글이"
    assert entity.persona == "다정한 곰"
    assert entity.personality == "다정한 성격"
    assert entity.speech_style == "존댓말"
    assert entity.background == "숲에서 옴"
    assert entity.image_url.endswith("x.png")
    assert entity.source_image_url is not None
    assert entity.created_at == fixed_now
    assert entity.character_id is not None


def test_source_url_is_none_for_text_only() -> None:
    entity = build(
        input=_input(),
        llm_result=_llm(),
        vlm_result=None,
        generated_image_url="https://s3/c.png",
        source_image_url=None,
        now=datetime(2026, 5, 22),
    )
    assert entity.source_image_url is None
```

- [ ] **Step 11.2: 구현**

`nodes/builder.py`:

```python
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
    VLMResult,
)


def build(
    *,
    input: CharacterCreationInput,
    llm_result: LLMPersonaResult,
    vlm_result: VLMResult | None,
    generated_image_url: str,
    source_image_url: str | None,
    now: datetime,
) -> CharacterEntity:
    del vlm_result
    return CharacterEntity(
        character_id=uuid4(),
        user_id=input.user_id,
        name=input.name,
        persona=input.persona,
        personality=llm_result.personality,
        speech_style=llm_result.speech_style,
        background=llm_result.background,
        image_url=generated_image_url,
        source_image_url=source_image_url,
        created_at=now,
    )
```

- [ ] **Step 11.3: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_builder.py --no-cov -v
```
Expected: 2 passed.

---

## Task 12: `repository.py` — 인메모리 fake

**Files:**
- Create: `agents/character_creation/repository.py`
- Create: `tests/agents/character_creation/test_repository.py`

본 PR 은 실제 DB 어댑터를 만들지 않는다. `protocols.CharacterRepositoryPort` 와 동일 시그니처의 인메모리 구현을 노출하여 호출자가 `pipeline.run` 에 주입할 수 있게 한다.

- [ ] **Step 12.1: 실패 테스트 작성**

```python
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from agents.character_creation.repository import InMemoryCharacterRepository
from agents.character_creation.schemas import CharacterEntity


def _entity(user_id: str = "u1") -> CharacterEntity:
    return CharacterEntity(
        character_id=uuid4(),
        user_id=user_id,
        name="몽글이",
        persona="p",
        personality="x",
        speech_style="y",
        background="z",
        image_url="https://s3/c.png",
        source_image_url=None,
        created_at=datetime(2026, 5, 22),
    )


async def test_active_count_starts_at_zero() -> None:
    repo = InMemoryCharacterRepository()
    assert await repo.count_active("u1") == 0


async def test_save_increments_active_count() -> None:
    repo = InMemoryCharacterRepository()
    await repo.save(_entity("u1"))
    await repo.save(_entity("u1"))
    await repo.save(_entity("u2"))
    assert await repo.count_active("u1") == 2
    assert await repo.count_active("u2") == 1


async def test_today_regen_count_is_caller_managed() -> None:
    repo = InMemoryCharacterRepository()
    assert await repo.today_regen_count("u1") == 0
    repo.set_regen_count("u1", 2)
    assert await repo.today_regen_count("u1") == 2


async def test_delete_image_keys_records_calls() -> None:
    repo = InMemoryCharacterRepository()
    await repo.delete_image_keys(["sources/u/a.png", "characters/u/b.png"])
    assert "sources/u/a.png" in repo.deleted_keys
    assert "characters/u/b.png" in repo.deleted_keys
```

- [ ] **Step 12.2: 구현**

`repository.py`:

```python
from __future__ import annotations

from collections import defaultdict

from agents.character_creation.schemas import CharacterEntity


class InMemoryCharacterRepository:
    def __init__(self) -> None:
        self._by_user: dict[str, list[CharacterEntity]] = defaultdict(list)
        self._regen_today: dict[str, int] = defaultdict(int)
        self.deleted_keys: list[str] = []

    async def count_active(self, user_id: str) -> int:
        return len(self._by_user[user_id])

    async def today_regen_count(self, user_id: str) -> int:
        return self._regen_today[user_id]

    def set_regen_count(self, user_id: str, value: int) -> None:
        self._regen_today[user_id] = value

    async def save(self, entity: CharacterEntity) -> None:
        self._by_user[entity.user_id].append(entity)

    async def delete_image_keys(self, keys: list[str]) -> None:
        self.deleted_keys.extend(keys)
```

- [ ] **Step 12.3: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_repository.py --no-cov -v
```
Expected: 4 passed.

---

## Task 13: `pipeline.py` — 오케스트레이션

**Files:**
- Create: `agents/character_creation/pipeline.py`
- Create: `tests/agents/character_creation/test_pipeline.py`

본 단계가 모든 노드를 엮는 핵심. **에이전트는 입력+포트만 받고 엔티티를 반환**. DB 저장은 호출자가 별도로 `ports.repository.save(entity)` 호출 (FEATURES.md §3.2 표준). 원본 업로드 후 이미지 생성/생성이미지 업로드 실패 시 `repository.delete_image_keys` 로 cleanup.

- [ ] **Step 13.1: 실패 테스트 작성**

```python
from __future__ import annotations

import pytest

from agents.character_creation.exceptions import (
    ImageGenerationFailedError,
    LLMFailedError,
    ValidationFailedError,
)
from agents.character_creation.pipeline import Ports, run
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from tests.agents.character_creation.fakes import (
    FakeCounter,
    FakeImageGenerator,
    FakeLLM,
    FakeRepository,
    FakeS3,
    FakeVLM,
)


def _ports(
    *,
    repo: FakeRepository | None = None,
    llm: FakeLLM | None = None,
    vlm: FakeVLM | None = None,
    s3: FakeS3 | None = None,
    img: FakeImageGenerator | None = None,
    counter: FakeCounter | None = None,
) -> Ports:
    return Ports(
        llm=llm or FakeLLM(),
        vlm=vlm or FakeVLM(),
        s3=s3 or FakeS3(),
        image_generator=img or FakeImageGenerator(),
        counter=counter or FakeCounter(),
        repository=repo or FakeRepository(),
    )


def _input(with_image: bool = False) -> CharacterCreationInput:
    src = (
        SourceImage(filename="a.png", content_type="image/png", data=b"\x89PNG")
        if with_image
        else None
    )
    return CharacterCreationInput(
        user_id="u1",
        name="몽글이",
        persona="다정한 곰",
        source_image=src,
    )


async def test_text_only_pipeline_returns_entity_without_source_url() -> None:
    ports = _ports()
    entity = await run(_input(), ports=ports, is_regeneration=False)
    assert entity.source_image_url is None
    assert entity.image_url.startswith("https://fake-s3.local/characters/u1/")
    assert ports.vlm.calls == 0  # type: ignore[attr-defined]


async def test_image_plus_text_pipeline_uploads_source_and_invokes_vlm() -> None:
    ports = _ports()
    entity = await run(_input(with_image=True), ports=ports, is_regeneration=False)
    assert entity.source_image_url is not None
    assert entity.source_image_url.startswith("https://fake-s3.local/sources/u1/")
    assert ports.vlm.calls == 1  # type: ignore[attr-defined]
    assert ports.image_generator.last_inputs["vlm_result"] is not None  # type: ignore[attr-defined]


async def test_vlm_failure_degrades_but_completes() -> None:
    ports = _ports(vlm=FakeVLM(fail_times=3))
    entity = await run(_input(with_image=True), ports=ports, is_regeneration=False)
    assert entity is not None
    assert ports.image_generator.last_inputs["vlm_result"] is None  # type: ignore[attr-defined]


async def test_validation_failure_does_not_call_external_services() -> None:
    ports = _ports(repo=FakeRepository(active_count=10))
    with pytest.raises(ValidationFailedError):
        await run(_input(), ports=ports, is_regeneration=False)
    assert ports.llm.calls == 0  # type: ignore[attr-defined]
    assert ports.image_generator.calls == 0  # type: ignore[attr-defined]


async def test_llm_failure_propagates_after_retries() -> None:
    ports = _ports(llm=FakeLLM(fail_times=3))
    with pytest.raises(LLMFailedError):
        await run(_input(), ports=ports, is_regeneration=False)


async def test_image_generator_failure_cleans_up_source_upload() -> None:
    s3 = FakeS3()
    repo = FakeRepository()
    ports = _ports(s3=s3, repo=repo, img=FakeImageGenerator(fail_times=2))
    with pytest.raises(ImageGenerationFailedError):
        await run(_input(with_image=True), ports=ports, is_regeneration=False)
    assert len(repo.deleted_keys) >= 1
    assert any(k.startswith("sources/u1/") for k in repo.deleted_keys)


async def test_regeneration_path_checks_daily_limit() -> None:
    ports = _ports(repo=FakeRepository(active_count=1, regen_count_today=3))
    with pytest.raises(ValidationFailedError) as exc:
        await run(_input(), ports=ports, is_regeneration=True)
    assert exc.value.code == "C2"
```

- [ ] **Step 13.2: 실패 확인 → 구현**

`pipeline.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from agents.character_creation import validation
from agents.character_creation.nodes import (
    builder,
    image_generator,
    image_upload,
    llm_persona,
    vlm_analyzer,
)
from agents.character_creation.protocols import (
    CharacterRepositoryPort,
    ImageGeneratorPort,
    LLMPort,
    RegenerationCounterPort,
    S3Port,
    VLMPort,
)
from agents.character_creation.router import RouteDecision, decide
from agents.character_creation.schemas import CharacterCreationInput, CharacterEntity


@dataclass
class Ports:
    llm: LLMPort
    vlm: VLMPort
    s3: S3Port
    image_generator: ImageGeneratorPort
    counter: RegenerationCounterPort
    repository: CharacterRepositoryPort


async def run(
    input: CharacterCreationInput,
    *,
    ports: Ports,
    is_regeneration: bool,
    now: datetime | None = None,
) -> CharacterEntity:
    await validation.check(input, repo=ports.repository, is_regeneration=is_regeneration)

    route = decide(input)
    source_key: str | None = None
    source_url: str | None = None

    llm_task = asyncio.create_task(
        llm_persona.generate(
            ports.llm, persona=input.persona, keywords=input.personality_keywords
        )
    )

    vlm_task: asyncio.Task | None = None
    if route is RouteDecision.IMAGE_AND_TEXT:
        assert input.source_image is not None
        source_url, source_key = await image_upload.store_source(
            ports.s3, image=input.source_image, user_id=input.user_id
        )
        vlm_task = asyncio.create_task(
            vlm_analyzer.extract(ports.vlm, image=input.source_image)
        )

    try:
        llm_result = await llm_task
        vlm_result = await vlm_task if vlm_task is not None else None

        image_bytes = await image_generator.generate_bytes(
            ports.image_generator,
            counter=ports.counter,
            user_id=input.user_id,
            llm_result=llm_result,
            vlm_result=vlm_result,
            fallback_persona=input.persona if vlm_result is None else None,
        )

        generated_url, _generated_key = await image_upload.store_generated(
            ports.s3, body=image_bytes, user_id=input.user_id
        )
    except Exception:
        if source_key is not None:
            await ports.repository.delete_image_keys([source_key])
        raise

    return builder.build(
        input=input,
        llm_result=llm_result,
        vlm_result=vlm_result,
        generated_image_url=generated_url,
        source_image_url=source_url,
        now=now or datetime.now(tz=timezone.utc),
    )
```

- [ ] **Step 13.3: 통과 확인**

Run:
```bash
pytest tests/agents/character_creation/test_pipeline.py --no-cov -v
```
Expected: 7 passed.

- [ ] **Step 13.4: 전체 테스트 + 커버리지 80% 확인**

Run:
```bash
pytest
```
Expected: 모든 테스트 통과 (≥ 36 passed), 커버리지 ≥ 80%, exit code 0.

미달 시 `pytest --cov=agents --cov-report=term-missing` 로 누락 라인 확인하여 테스트 보강.

- [ ] **Step 13.5: `agents/character_creation/__init__.py` 에 entry export**

```python
from agents.character_creation.pipeline import Ports, run
from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
    PersonalityKeyword,
    SourceImage,
    VLMResult,
)

__all__ = [
    "CharacterCreationInput",
    "CharacterEntity",
    "LLMPersonaResult",
    "PersonalityKeyword",
    "Ports",
    "SourceImage",
    "VLMResult",
    "run",
]
```

Run:
```bash
python -c "from agents.character_creation import run, Ports, CharacterCreationInput; print('ok')"
```
Expected: `ok`.

---

## Task 14: DoD 마무리 — architecture.mmd / CLAUDE.md / CHANGELOG / TODO / decisions.md

**Files:**
- Modify: `docs/features/character_generation/architecture.mmd`
- Modify: `docs/features/character_generation/CLAUDE.md` (§8 만)
- Modify: `CHANGELOG.md`
- Modify: `docs/TODO.md`
- Create: `agents/character_creation/decisions.md`

- [ ] **Step 14.1: as-built mmd 갱신**

`docs/features/character_generation/architecture.mmd` 의 다음 노드 라벨을 갱신:

1. `G["VLM / Image Analyzer ..."]` → `재시도 2회, 실패 시 외형 정보 없이 진행`, 출력 `외형 특징 추출 | null` 표기.
2. `E["LLM ..."]` → `(재시도 2회)` 추가.
3. `H["캐릭터 이미지 생성 ..."]` → `(재시도 1회, 호출 직전 img_gen_logs +1)` 추가, 입력 라벨에 `VLM 외형 특징 (optional)` 표기.
4. `D -- 원본 이미지 저장 -->` edge 라벨에 `(재시도 3회)` 추가.

검증:
```bash
grep -c "재시도" docs/features/character_generation/architecture.mmd
```
Expected: `>= 3`.

- [ ] **Step 14.2: 피처 CLAUDE.md §8 "미결 사항" 갱신**

`docs/features/character_generation/CLAUDE.md` 의 `## 8. 미결 사항 (Open Questions)` 섹션 전체를 다음으로 교체:

```markdown
## 8. 결정 사항 (Resolved)

본 피처 첫 구현(`agents/character_creation/`) 시점에 다음과 같이 결정되었다. 코드 결정은 `agents/character_creation/decisions.md` 참조.

1. **이미지 생성 모델 선택** — 단일 `ImageGeneratorPort` Protocol. text-only / image-input 분기는 어댑터 내부 책임.
2. **재생성 카운트 정의** — 이미지 생성 호출 1회 = 재생성 1회. 호출 직전 `img_gen_logs.gen_cnt` +1 (재시도는 카운트하지 않음).
3. **VLM 실패 시 정책** — degrade-on-fail. 재시도 2회 모두 실패 시 외형 정보 없이 LLM 결과 + 페르소나 텍스트로 진행.
4. **병렬 처리 범위** — LLM 과 VLM 은 `asyncio.gather` 로 병렬. S3 원본 업로드는 VLM 직전에 순차.
5. **이미지 생성 프롬프트 조립** — `ImageGenerator.generate` 어댑터 내부에서 조립. 파이프라인은 구조화 입력만 전달.
```

- [ ] **Step 14.3: `agents/character_creation/decisions.md` 작성**

```markdown
# character_creation — 결정 사항 로그

본 파일은 캐릭터 생성 에이전트 구현 시 내린 코드 결정사항을 영구 기록한다.

## 2026-05-22 — 초기 구현

1. **포트 분리** — 외부 의존(LLM/VLM/S3/Image Generator/Counter/Repository)을 모두 Protocol 로 추상화. 실제 어댑터는 후속 PR.
2. **에이전트 순수성** — `pipeline.run` 은 DB 저장을 수행하지 않고 `CharacterEntity` 만 반환한다 (`docs/FEATURES.md` §3.2 책임 분리). 저장은 호출자가 `ports.repository.save(entity)` 로 수행.
3. **이미지 생성 실패 시 cleanup** — 원본 업로드가 성공한 뒤 이미지 생성/생성이미지 업로드가 실패하면 파이프라인이 `repository.delete_image_keys([source_key])` 를 호출하여 고아 파일을 막는다. DB 저장 자체 실패에 대한 cleanup 은 호출자 책임.
4. **degrade-on-fail (VLM)** — `docs/features/character_generation/CLAUDE.md` §8 #3 결정에 따라 VLM 재시도 소진 시 None 반환, 파이프라인은 `fallback_persona` 로 이미지 생성을 계속한다.
5. **재시도 회수** — `AI_RULES.md` §3 표 준수. LLM=2, VLM=2, S3=3, ImageGen=1.
6. **타임존** — `now` 미주입 시 UTC 기준. DB 저장 시점에 호출자가 KST 변환 책임.
```

- [ ] **Step 14.4: `CHANGELOG.md` 항목 추가**

`## [Unreleased]` 섹션 바로 아래에 추가:

```markdown
## [Unreleased]
### Added
- `agents/character_creation/` 초기 구현 — Validation → Router → LLM·VLM·S3 업로드 (병렬) → 이미지 생성 → 빌드 파이프라인. 외부 의존은 Protocol 포트로 추상화, 테스트는 인메모리 페이크로 검증 (커버리지 80%+).
- 피처 결정사항 `agents/character_creation/decisions.md` 신규 — 포트 분리, 에이전트 순수성, cleanup 책임, VLM degrade-on-fail.
- `docs/features/character_generation/architecture.mmd` as-built 갱신 (재시도 횟수 / VLM 옵셔널 / img_gen_logs 카운터 표기).

### Changed
- `docs/features/character_generation/CLAUDE.md` §8 "미결 사항" → "결정 사항" 으로 갱신.
- 프로젝트 의존성·테스트 도구 정의: `pyproject.toml` 신규 (pydantic≥2, pytest + asyncio + cov, 커버리지 게이트 80%).
```

- [ ] **Step 14.5: `docs/TODO.md` 완료 항목 추가**

`## 완료` 섹션 끝에 추가:

```markdown
- [x] 2026-05-22 — character_creation 에이전트 초기 구현 (포트 분리 / TDD / 커버리지 80%+ / 피처 §8 미결 사항 5건 해소)
```

- [ ] **Step 14.6: DoD 5항목 일괄 검증 (병렬 실행)**

Run all in parallel:

```bash
pytest
grep -c "재시도\|optional\|img_gen_logs" docs/features/character_generation/architecture.mmd
grep -c "character_creation" CHANGELOG.md
grep -c "결정 사항\|Resolved" docs/features/character_generation/CLAUDE.md
grep "character_creation" docs/TODO.md
```

Expected:
- pytest: 전부 PASS, coverage ≥ 80%
- architecture.mmd: `>= 3`
- CHANGELOG: `>= 1`
- CLAUDE.md: `>= 1`
- TODO: 매칭 1줄

---

## Self-Review (작성자 자체 점검)

**1. 스펙 커버리지** (`docs/features/character_generation/CLAUDE.md`):

| 스펙 § | 항목 | 대응 Task |
|---|---|---|
| §2.1 Input | Pydantic 모델 | Task 2 |
| §2.2 Output | `CharacterEntity` 스키마 | Task 2 |
| §3 C1~C4 | Validation | Task 5 |
| §3 C5 | 중간 산출물 미저장 (entity 에 vlm 미반영) | Task 11 builder |
| §3 C6 | 8bit 픽셀 출력 — ImageGenerator 어댑터 책임 (포트로 추상화) | Task 4 protocols |
| §5.1 Validation | `validation.check` | Task 5 |
| §5.2 Router | `router.decide` | Task 6 |
| §5.3 Text Pipeline (LLM) | `nodes/llm_persona.generate` | Task 7 |
| §5.4 Image Pipeline | `nodes/image_upload.store_source` | Task 8 |
| §5.5 VLM | `nodes/vlm_analyzer.extract` + degrade | Task 9 |
| §5.6 이미지 생성 | `nodes/image_generator.generate_bytes` | Task 10 |
| §5.7 빌드 | `nodes/builder.build` | Task 11 |
| §5.8 DB 저장 | `repository.InMemoryCharacterRepository` + 호출자 위임 | Task 12 |
| §6.1 디렉토리 | `agents/character_creation/{pipeline,validation,router,nodes/*,repository,schemas,exceptions}.py` | Task 1~13 |
| §6.2 인터페이스 스케치 | `Ports`, `run(input, *, ports, is_regeneration)` | Task 13 |
| §7 재시도 표 | LLM 2 / VLM 2 (degrade) / S3 3 / ImageGen 1 | Tasks 7~10 |
| §7 원자성 (cleanup) | source_key cleanup on later failure | Task 13 |
| §8 미결 사항 5건 | Resolved | §0 + Task 14 |

`AI_RULES.md` 커버리지:
- §1 모델 선택 — 포트 추상화로 위임 (어댑터에서 명시)
- §2 구조화 출력 — Pydantic `LLMPersonaResult` 강제
- §3 재시도 표 — 노드별 상수
- §6 컨텍스트 격리 — VLM/LLM 입력에 다른 사용자 정보 없음
- §7 토큰·비용 — 재생성 일 3회 검증 (Task 5)
- §8 실패 처리 패턴 — 4xx(`ValidationFailedError`) / 5xx(`ExternalServiceError`) 분리
- §9 보안 — 사용자 입력은 Pydantic 검증, 로그 미작성 (어댑터 책임)

`docs/FEATURES.md` §3 패턴 준수:
- §3.1 I/O 계약 (Pydantic, schemas.py 분리)
- §3.2 에이전트 vs 호출자 책임 분리 (저장은 호출자, cleanup 콜백 위임)
- §3.3 표준 파이프라인 순서 (Validation → 외부 호출 → 빌드 → (영속화는 호출자))
- §3.4 디렉토리 레이아웃

**2. Placeholder 점검:** "TBD/TODO/implement later" 없음. 모든 step 에 실제 코드/명령/기대 출력 제시.

**3. 식별자·시그니처 일관성 점검:**

| 식별자 | 정의 Task | 사용 Task |
|---|---|---|
| `CharacterCreationInput` | T2 | T5, T6, T11, T13 |
| `CharacterEntity` | T2 | T11, T12, T13 |
| `LLMPersonaResult` | T2 | T7, T10, T11 |
| `VLMResult` | T2 | T9, T10, T11 |
| `SourceImage` | T2 | T5, T6, T8, T9, T13 |
| `Ports` | T13 | T13 (테스트) |
| `RouteDecision.{TEXT_ONLY, IMAGE_AND_TEXT}` | T6 | T13 |
| `validation.check(input, *, repo, is_regeneration)` | T5 | T13 |
| `llm_persona.generate(llm, *, persona, keywords)` | T7 | T13 |
| `image_upload.store_source(s3, *, image, user_id)` → `(url, key)` | T8 | T13 |
| `image_upload.store_generated(s3, *, body, user_id)` → `(url, key)` | T8 | T13 |
| `vlm_analyzer.extract(vlm, *, image)` → `VLMResult \| None` | T9 | T13 |
| `image_generator.generate_bytes(..., counter=, vlm_result=, fallback_persona=)` | T10 | T13 |
| `builder.build(*, input, llm_result, vlm_result, generated_image_url, source_image_url, now)` | T11 | T13 |
| `CharacterRepositoryPort.{count_active, today_regen_count, save, delete_image_keys}` | T4 | T5, T12, T13 |

모두 일관. 시그니처가 정의 위치와 호출 위치에서 일치한다.
