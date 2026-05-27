# Feed Generation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `agents/feed_generation/` — 8-node LangGraph 파이프라인으로 완료된 퀘스트 + 캐릭터를 받아 Img2Img 피드 이미지(S3)와 한국어 캡션(LLM, ≤140자)을 생성한다.

**Architecture:** 직렬 LangGraph 파이프라인 (validate → assemble_image_prompt → img2img → s3_upload → assemble_caption_ctx → llm_caption → validate_caption → builder). Img2Img는 캐릭터 기존 S3 이미지를 reference로 사용. LLM(Mi:dm)은 퀘스트 컨텍스트 + 캐릭터 페르소나로 한국어 캡션 생성. img2img/s3_upload/llm_caption 노드에 RetryPolicy(max_attempts=3) 적용.

**Tech Stack:** Python, LangGraph, Pydantic v2, asyncio, openai(Mi:dm OpenAI-compatible), pytest

---

### Task 1: 디렉토리 스캐폴딩 + 예외 + 스키마

**Files:**
- Create: `agents/feed_generation/__init__.py`
- Create: `agents/feed_generation/exceptions.py`
- Create: `agents/feed_generation/schemas.py`
- Create: `agents/feed_generation/nodes/__init__.py`
- Create: `tests/agents/feed_generation/__init__.py`
- Test: `tests/agents/feed_generation/test_schemas.py`

- [ ] **Step 1: 디렉토리와 빈 __init__ 파일 생성**

```bash
mkdir -p agents/feed_generation/nodes
mkdir -p tests/agents/feed_generation
touch agents/feed_generation/__init__.py
touch agents/feed_generation/nodes/__init__.py
touch tests/agents/feed_generation/__init__.py
```

- [ ] **Step 2: 실패하는 스키마 테스트 작성**

```python
# tests/agents/feed_generation/test_schemas.py
from uuid import uuid4
import pytest
from pydantic import ValidationError
from agents.feed_generation.schemas import (
    QuestRef,
    CharacterRef,
    FeedGenerationInput,
    GeneratedFeed,
)


def test_quest_ref_rejects_empty_text():
    with pytest.raises(ValidationError):
        QuestRef(quest_id=uuid4(), quest_text="")


def test_character_ref_requires_image_url():
    with pytest.raises(ValidationError):
        CharacterRef(
            character_id=uuid4(),
            name="몽글이",
            personality="밝음",
            speech_style="반말",
            appearance_keywords=["분홍 머리"],
        )


def test_feed_generation_input_rejects_extra_fields():
    with pytest.raises(ValidationError):
        FeedGenerationInput(
            quest={"quest_id": str(uuid4()), "quest_text": "청소"},
            character={
                "character_id": str(uuid4()),
                "name": "몽글이",
                "personality": "밝음",
                "speech_style": "반말",
                "appearance_keywords": [],
                "image_url": "https://s3.example.com/c.png",
            },
            extra_field="bad",
        )


def test_generated_feed_rejects_caption_over_140():
    with pytest.raises(ValidationError):
        GeneratedFeed(
            character_id=uuid4(),
            quest_id=uuid4(),
            image_url="https://s3.example.com/f.png",
            caption="가" * 141,
        )


def test_generated_feed_accepts_caption_at_140():
    feed = GeneratedFeed(
        character_id=uuid4(),
        quest_id=uuid4(),
        image_url="https://s3.example.com/f.png",
        caption="가" * 140,
    )
    assert len(feed.caption) == 140
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/agents/feed_generation/test_schemas.py -v
```
Expected: ImportError (모듈 없음)

- [ ] **Step 4: exceptions.py 작성**

```python
# agents/feed_generation/exceptions.py


class FeedGenerationError(Exception): ...


class InputValidationError(FeedGenerationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ImageGenerationError(FeedGenerationError): ...


class S3UploadError(FeedGenerationError): ...


class CaptionGenerationError(FeedGenerationError): ...


class CaptionValidationError(FeedGenerationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

- [ ] **Step 5: schemas.py 작성**

```python
# agents/feed_generation/schemas.py
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QuestRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest_id: UUID
    quest_text: Annotated[str, Field(min_length=1, max_length=300)]


class CharacterRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=50)]
    personality: str
    speech_style: str
    appearance_keywords: list[str]
    image_url: str


class FeedGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest: QuestRef
    character: CharacterRef


class GeneratedFeed(BaseModel):
    character_id: UUID
    quest_id: UUID
    image_url: str
    caption: Annotated[str, Field(max_length=140)]
```

- [ ] **Step 6: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_schemas.py -v
```
Expected: 5 passed

- [ ] **Step 7: 커밋**

```bash
git add agents/feed_generation/ tests/agents/feed_generation/
git commit -m "feat(feed_generation): add exceptions and schemas"
```

---

### Task 2: Protocols, State, Test Fakes

**Files:**
- Create: `agents/feed_generation/protocols.py`
- Create: `agents/feed_generation/state.py`
- Create: `tests/agents/feed_generation/fakes.py`

- [ ] **Step 1: protocols.py 작성**

```python
# agents/feed_generation/protocols.py
from dataclasses import dataclass
from typing import Protocol


class LLMPort(Protocol):
    async def generate(self, prompt: str) -> str: ...


class ImageGeneratorPort(Protocol):
    async def generate_img2img(self, reference_url: str, prompt: str) -> bytes: ...


class S3Port(Protocol):
    async def upload(self, key: str, data: bytes) -> str: ...


@dataclass
class Ports:
    llm: LLMPort
    image_generator: ImageGeneratorPort
    s3: S3Port
```

- [ ] **Step 2: state.py 작성**

```python
# agents/feed_generation/state.py
from typing import TypedDict

from agents.feed_generation.schemas import FeedGenerationInput, GeneratedFeed


class FeedGraphState(TypedDict):
    input: FeedGenerationInput
    image_prompt: str | None
    raw_image: bytes | None
    image_url: str | None
    caption_ctx: str | None
    raw_caption: str | None
    result: GeneratedFeed | None
```

- [ ] **Step 3: fakes.py 작성**

```python
# tests/agents/feed_generation/fakes.py
from uuid import uuid4

from agents.feed_generation.exceptions import (
    CaptionGenerationError,
    ImageGenerationError,
    S3UploadError,
)
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import CharacterRef, FeedGenerationInput, QuestRef
from agents.feed_generation.state import FeedGraphState


def make_input(**overrides) -> FeedGenerationInput:
    data = dict(
        quest=QuestRef(quest_id=uuid4(), quest_text="방 청소하기"),
        character=CharacterRef(
            character_id=uuid4(),
            name="몽글이",
            personality="밝고 활발함",
            speech_style="반말, 이모티콘 자주 사용",
            appearance_keywords=["분홍색 머리", "큰 눈", "귀여운"],
            image_url="https://s3.example.com/characters/test.png",
        ),
    )
    data.update(overrides)
    return FeedGenerationInput(**data)


def make_state(**overrides) -> FeedGraphState:
    defaults: FeedGraphState = {
        "input": make_input(),
        "image_prompt": None,
        "raw_image": None,
        "image_url": None,
        "caption_ctx": None,
        "raw_caption": None,
        "result": None,
    }
    defaults.update(overrides)
    return defaults


class FakeLLM:
    def __init__(self, caption: str = "오늘 방 청소 완료! 기분 최고 ✨") -> None:
        self.caption = caption
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.caption


class FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise CaptionGenerationError("LLM 서버 오류")


class FakeImageGenerator:
    def __init__(self, image_bytes: bytes = b"fake_image_bytes") -> None:
        self.image_bytes = image_bytes
        self.calls: list[tuple[str, str]] = []

    async def generate_img2img(self, reference_url: str, prompt: str) -> bytes:
        self.calls.append((reference_url, prompt))
        return self.image_bytes


class FailingImageGenerator:
    async def generate_img2img(self, reference_url: str, prompt: str) -> bytes:
        raise ImageGenerationError("이미지 생성 서버 오류")


class FakeS3:
    def __init__(self, url: str = "https://s3.example.com/feeds/result.png") -> None:
        self.url = url
        self.calls: list[tuple[str, bytes]] = []

    async def upload(self, key: str, data: bytes) -> str:
        self.calls.append((key, data))
        return self.url


class FailingS3:
    async def upload(self, key: str, data: bytes) -> str:
        raise S3UploadError("S3 연결 오류")


def make_ports(**overrides) -> Ports:
    defaults = dict(
        llm=FakeLLM(),
        image_generator=FakeImageGenerator(),
        s3=FakeS3(),
    )
    defaults.update(overrides)
    return Ports(**defaults)
```

- [ ] **Step 4: import 검증**

```bash
uv run python -c "
from agents.feed_generation.protocols import Ports
from agents.feed_generation.state import FeedGraphState
from tests.agents.feed_generation.fakes import make_state, make_ports
print('OK')
"
```
Expected: OK

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/protocols.py agents/feed_generation/state.py tests/agents/feed_generation/fakes.py
git commit -m "feat(feed_generation): add protocols, state, test fakes"
```

---

### Task 3: validate 노드

**Files:**
- Create: `agents/feed_generation/nodes/validate.py`
- Test: `tests/agents/feed_generation/test_node_validate.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/agents/feed_generation/test_node_validate.py
from uuid import uuid4
import pytest
from agents.feed_generation.exceptions import InputValidationError
from agents.feed_generation.nodes.validate import validate_node
from agents.feed_generation.schemas import CharacterRef, FeedGenerationInput, QuestRef
from tests.agents.feed_generation.fakes import make_state


async def test_validate_valid_input_routes_to_assemble_image_prompt():
    state = make_state()
    cmd = await validate_node(state, {})
    assert cmd.goto == "assemble_image_prompt"


async def test_validate_empty_image_url_raises():
    state = make_state(
        input=FeedGenerationInput(
            quest=QuestRef(quest_id=uuid4(), quest_text="청소"),
            character=CharacterRef(
                character_id=uuid4(),
                name="몽글",
                personality="밝음",
                speech_style="반말",
                appearance_keywords=[],
                image_url="   ",
            ),
        )
    )
    with pytest.raises(InputValidationError) as exc_info:
        await validate_node(state, {})
    assert exc_info.value.code == "empty_image_url"


async def test_validate_empty_quest_text_is_caught_by_pydantic():
    with pytest.raises(Exception):
        FeedGenerationInput(
            quest=QuestRef(quest_id=uuid4(), quest_text=""),
            character=CharacterRef(
                character_id=uuid4(),
                name="몽글",
                personality="밝음",
                speech_style="반말",
                appearance_keywords=[],
                image_url="https://s3.example.com/c.png",
            ),
        )
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_validate.py -v
```
Expected: ImportError

- [ ] **Step 3: validate.py 구현**

```python
# agents/feed_generation/nodes/validate.py
from typing import Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import InputValidationError
from agents.feed_generation.state import FeedGraphState

_Target = Literal["assemble_image_prompt"]


async def validate_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    if not state["input"].character.image_url.strip():
        raise InputValidationError(
            code="empty_image_url",
            message="character.image_url must not be blank",
        )
    return Command(goto="assemble_image_prompt")
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_validate.py -v
```
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/nodes/validate.py tests/agents/feed_generation/test_node_validate.py
git commit -m "feat(feed_generation): add validate node"
```

---

### Task 4: assemble_image_prompt 노드

**Files:**
- Create: `agents/feed_generation/nodes/assemble_image_prompt.py`
- Test: `tests/agents/feed_generation/test_node_assemble_image_prompt.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/agents/feed_generation/test_node_assemble_image_prompt.py
from agents.feed_generation.nodes.assemble_image_prompt import (
    assemble_image_prompt_node,
    _build_image_prompt,
)
from tests.agents.feed_generation.fakes import make_state, make_input


async def test_assemble_image_prompt_sets_prompt_and_routes_to_img2img():
    state = make_state()
    cmd = await assemble_image_prompt_node(state, {})
    assert cmd.goto == "img2img"
    assert cmd.update["image_prompt"]
    assert isinstance(cmd.update["image_prompt"], str)
    assert len(cmd.update["image_prompt"]) > 0


async def test_image_prompt_includes_appearance_keywords():
    inp = make_input()
    prompt = _build_image_prompt(inp.character, inp.quest)
    for kw in inp.character.appearance_keywords:
        assert kw in prompt


async def test_image_prompt_includes_quest_text():
    inp = make_input()
    prompt = _build_image_prompt(inp.character, inp.quest)
    assert inp.quest.quest_text in prompt
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_assemble_image_prompt.py -v
```
Expected: ImportError

- [ ] **Step 3: assemble_image_prompt.py 구현**

```python
# agents/feed_generation/nodes/assemble_image_prompt.py
from typing import Literal

from langgraph.types import Command

from agents.feed_generation.schemas import CharacterRef, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["img2img"]


def _build_image_prompt(character: CharacterRef, quest: QuestRef) -> str:
    keywords = ", ".join(character.appearance_keywords)
    return (
        f"{keywords}, performing task: {quest.quest_text}, "
        "anime style, detailed illustration, vibrant colors"
    )


async def assemble_image_prompt_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    prompt = _build_image_prompt(state["input"].character, state["input"].quest)
    return Command(update={"image_prompt": prompt}, goto="img2img")
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_assemble_image_prompt.py -v
```
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/nodes/assemble_image_prompt.py tests/agents/feed_generation/test_node_assemble_image_prompt.py
git commit -m "feat(feed_generation): add assemble_image_prompt node"
```

---

### Task 5: img2img 노드

**Files:**
- Create: `agents/feed_generation/nodes/img2img.py`
- Test: `tests/agents/feed_generation/test_node_img2img.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/agents/feed_generation/test_node_img2img.py
import pytest
from agents.feed_generation.exceptions import ImageGenerationError
from agents.feed_generation.nodes.img2img import img2img_node
from tests.agents.feed_generation.fakes import (
    FakeImageGenerator,
    FailingImageGenerator,
    make_ports,
    make_state,
)


async def test_img2img_node_sets_raw_image_and_routes_to_s3_upload():
    fake_gen = FakeImageGenerator(image_bytes=b"img_data")
    ports = make_ports(image_generator=fake_gen)
    state = make_state(image_prompt="분홍 머리, anime style")
    config = {"configurable": {"ports": ports}}

    cmd = await img2img_node(state, config)

    assert cmd.goto == "s3_upload"
    assert cmd.update["raw_image"] == b"img_data"


async def test_img2img_node_passes_reference_url_and_prompt():
    fake_gen = FakeImageGenerator()
    ports = make_ports(image_generator=fake_gen)
    state = make_state(image_prompt="분홍 머리, anime style")
    config = {"configurable": {"ports": ports}}

    await img2img_node(state, config)

    assert fake_gen.calls[0][0] == state["input"].character.image_url
    assert fake_gen.calls[0][1] == "분홍 머리, anime style"


async def test_img2img_node_wraps_port_error_as_image_generation_error():
    ports = make_ports(image_generator=FailingImageGenerator())
    state = make_state(image_prompt="prompt")
    config = {"configurable": {"ports": ports}}

    with pytest.raises(ImageGenerationError):
        await img2img_node(state, config)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_img2img.py -v
```
Expected: ImportError

- [ ] **Step 3: img2img.py 구현**

```python
# agents/feed_generation/nodes/img2img.py
from typing import Any, Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import ImageGenerationError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.state import FeedGraphState

_Target = Literal["s3_upload"]


async def img2img_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    try:
        raw_image = await ports.image_generator.generate_img2img(
            state["input"].character.image_url,
            state["image_prompt"],
        )
    except ImageGenerationError:
        raise
    except Exception as exc:
        raise ImageGenerationError(str(exc)) from exc
    return Command(update={"raw_image": raw_image}, goto="s3_upload")
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_img2img.py -v
```
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/nodes/img2img.py tests/agents/feed_generation/test_node_img2img.py
git commit -m "feat(feed_generation): add img2img node"
```

---

### Task 6: s3_upload 노드

**Files:**
- Create: `agents/feed_generation/nodes/s3_upload.py`
- Test: `tests/agents/feed_generation/test_node_s3_upload.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/agents/feed_generation/test_node_s3_upload.py
import pytest
from agents.feed_generation.exceptions import S3UploadError
from agents.feed_generation.nodes.s3_upload import s3_upload_node
from tests.agents.feed_generation.fakes import (
    FakeS3,
    FailingS3,
    make_ports,
    make_state,
)


async def test_s3_upload_node_sets_image_url_and_routes_to_assemble_caption_ctx():
    fake_s3 = FakeS3(url="https://s3.example.com/feeds/out.png")
    ports = make_ports(s3=fake_s3)
    state = make_state(raw_image=b"img_data")
    config = {"configurable": {"ports": ports}}

    cmd = await s3_upload_node(state, config)

    assert cmd.goto == "assemble_caption_ctx"
    assert cmd.update["image_url"] == "https://s3.example.com/feeds/out.png"


async def test_s3_upload_node_uses_character_and_quest_ids_in_key():
    fake_s3 = FakeS3()
    ports = make_ports(s3=fake_s3)
    state = make_state(raw_image=b"img_data")
    config = {"configurable": {"ports": ports}}

    await s3_upload_node(state, config)

    key = fake_s3.calls[0][0]
    assert str(state["input"].character.character_id) in key
    assert str(state["input"].quest.quest_id) in key


async def test_s3_upload_node_wraps_port_error_as_s3_upload_error():
    ports = make_ports(s3=FailingS3())
    state = make_state(raw_image=b"img_data")
    config = {"configurable": {"ports": ports}}

    with pytest.raises(S3UploadError):
        await s3_upload_node(state, config)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_s3_upload.py -v
```
Expected: ImportError

- [ ] **Step 3: s3_upload.py 구현**

```python
# agents/feed_generation/nodes/s3_upload.py
from typing import Any, Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import S3UploadError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.state import FeedGraphState

_Target = Literal["assemble_caption_ctx"]


async def s3_upload_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    character_id = state["input"].character.character_id
    quest_id = state["input"].quest.quest_id
    key = f"feeds/{character_id}/{quest_id}.png"
    try:
        image_url = await ports.s3.upload(key, state["raw_image"])
    except S3UploadError:
        raise
    except Exception as exc:
        raise S3UploadError(str(exc)) from exc
    return Command(update={"image_url": image_url}, goto="assemble_caption_ctx")
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_s3_upload.py -v
```
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/nodes/s3_upload.py tests/agents/feed_generation/test_node_s3_upload.py
git commit -m "feat(feed_generation): add s3_upload node"
```

---

### Task 7: assemble_caption_ctx 노드

**Files:**
- Create: `agents/feed_generation/nodes/assemble_caption_ctx.py`
- Test: `tests/agents/feed_generation/test_node_assemble_caption_ctx.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/agents/feed_generation/test_node_assemble_caption_ctx.py
from agents.feed_generation.nodes.assemble_caption_ctx import (
    assemble_caption_ctx_node,
    _build_caption_prompt,
)
from tests.agents.feed_generation.fakes import make_state, make_input


async def test_assemble_caption_ctx_sets_prompt_and_routes_to_llm_caption():
    state = make_state(image_prompt="분홍 머리, anime style")
    cmd = await assemble_caption_ctx_node(state, {})

    assert cmd.goto == "llm_caption"
    assert cmd.update["caption_ctx"]
    assert isinstance(cmd.update["caption_ctx"], str)


async def test_caption_prompt_includes_character_speech_style():
    inp = make_input()
    prompt = _build_caption_prompt(inp.character, inp.quest, "분홍 머리, anime")
    assert inp.character.speech_style in prompt


async def test_caption_prompt_includes_quest_text():
    inp = make_input()
    prompt = _build_caption_prompt(inp.character, inp.quest, "분홍 머리, anime")
    assert inp.quest.quest_text in prompt


async def test_caption_prompt_includes_image_prompt():
    inp = make_input()
    image_prompt = "분홍 머리, 큰 눈, anime"
    prompt = _build_caption_prompt(inp.character, inp.quest, image_prompt)
    assert image_prompt in prompt
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_assemble_caption_ctx.py -v
```
Expected: ImportError

- [ ] **Step 3: assemble_caption_ctx.py 구현**

```python
# agents/feed_generation/nodes/assemble_caption_ctx.py
from typing import Literal

from langgraph.types import Command

from agents.feed_generation.schemas import CharacterRef, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["llm_caption"]


def _build_caption_prompt(character: CharacterRef, quest: QuestRef, image_prompt: str) -> str:
    return (
        f"당신은 '{character.name}'이라는 캐릭터입니다.\n"
        f"성격: {character.personality}\n"
        f"말투: {character.speech_style}\n\n"
        f"방금 완료한 퀘스트: {quest.quest_text}\n"
        f"이미지 분위기: {image_prompt}\n\n"
        "위 퀘스트를 완료하고 느낀 소감을 캐릭터의 말투로 한국어 SNS 캡션으로 써주세요.\n"
        "규칙: 반드시 한국어로만 작성, 140자 이하, 캡션 텍스트만 출력"
    )


async def assemble_caption_ctx_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    prompt = _build_caption_prompt(
        state["input"].character,
        state["input"].quest,
        state["image_prompt"],
    )
    return Command(update={"caption_ctx": prompt}, goto="llm_caption")
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_assemble_caption_ctx.py -v
```
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/nodes/assemble_caption_ctx.py tests/agents/feed_generation/test_node_assemble_caption_ctx.py
git commit -m "feat(feed_generation): add assemble_caption_ctx node"
```

---

### Task 8: llm_caption 노드

**Files:**
- Create: `agents/feed_generation/nodes/llm_caption.py`
- Test: `tests/agents/feed_generation/test_node_llm_caption.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/agents/feed_generation/test_node_llm_caption.py
import pytest
from agents.feed_generation.exceptions import CaptionGenerationError
from agents.feed_generation.nodes.llm_caption import llm_caption_node
from tests.agents.feed_generation.fakes import (
    FakeLLM,
    FailingLLM,
    make_ports,
    make_state,
)


async def test_llm_caption_node_sets_raw_caption_and_routes_to_validate_caption():
    fake_llm = FakeLLM(caption="청소 완료! ✨")
    ports = make_ports(llm=fake_llm)
    state = make_state(caption_ctx="당신은 몽글이입니다...")
    config = {"configurable": {"ports": ports}}

    cmd = await llm_caption_node(state, config)

    assert cmd.goto == "validate_caption"
    assert cmd.update["raw_caption"] == "청소 완료! ✨"


async def test_llm_caption_node_passes_full_prompt_to_llm():
    fake_llm = FakeLLM()
    ports = make_ports(llm=fake_llm)
    state = make_state(caption_ctx="테스트 프롬프트")
    config = {"configurable": {"ports": ports}}

    await llm_caption_node(state, config)

    assert fake_llm.calls[0] == "테스트 프롬프트"


async def test_llm_caption_node_wraps_port_error_as_caption_generation_error():
    ports = make_ports(llm=FailingLLM())
    state = make_state(caption_ctx="프롬프트")
    config = {"configurable": {"ports": ports}}

    with pytest.raises(CaptionGenerationError):
        await llm_caption_node(state, config)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_llm_caption.py -v
```
Expected: ImportError

- [ ] **Step 3: llm_caption.py 구현**

```python
# agents/feed_generation/nodes/llm_caption.py
from typing import Any, Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import CaptionGenerationError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.state import FeedGraphState

_Target = Literal["validate_caption"]


async def llm_caption_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    try:
        raw_caption = await ports.llm.generate(state["caption_ctx"])
    except CaptionGenerationError:
        raise
    except Exception as exc:
        raise CaptionGenerationError(str(exc)) from exc
    return Command(update={"raw_caption": raw_caption}, goto="validate_caption")
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_llm_caption.py -v
```
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/nodes/llm_caption.py tests/agents/feed_generation/test_node_llm_caption.py
git commit -m "feat(feed_generation): add llm_caption node"
```

---

### Task 9: validate_caption 노드

**Files:**
- Create: `agents/feed_generation/nodes/validate_caption.py`
- Test: `tests/agents/feed_generation/test_node_validate_caption.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/agents/feed_generation/test_node_validate_caption.py
import pytest
from agents.feed_generation.exceptions import CaptionValidationError
from agents.feed_generation.nodes.validate_caption import validate_caption_node, check_caption
from tests.agents.feed_generation.fakes import make_state


async def test_validate_caption_valid_routes_to_builder():
    state = make_state(raw_caption="오늘 방 청소 완료! 기분 좋다 ✨")
    cmd = await validate_caption_node(state, {})
    assert cmd.goto == "builder"


async def test_validate_caption_rejects_over_140_chars():
    with pytest.raises(CaptionValidationError) as exc_info:
        check_caption("가" * 141)
    assert exc_info.value.code == "caption_too_long"


async def test_validate_caption_accepts_exactly_140_chars():
    check_caption("가" * 140)  # should not raise


async def test_validate_caption_rejects_no_korean():
    with pytest.raises(CaptionValidationError) as exc_info:
        check_caption("Cleaned my room! Great day!")
    assert exc_info.value.code == "no_korean"


async def test_validate_caption_accepts_mixed_korean_and_emoji():
    check_caption("청소 완료! ✨🎉")  # should not raise
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_validate_caption.py -v
```
Expected: ImportError

- [ ] **Step 3: validate_caption.py 구현**

```python
# agents/feed_generation/nodes/validate_caption.py
import re
from typing import Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import CaptionValidationError
from agents.feed_generation.state import FeedGraphState

_KOREAN_RE = re.compile(r"[가-힣]")
_Target = Literal["builder"]


def check_caption(caption: str) -> None:
    if len(caption) > 140:
        raise CaptionValidationError(
            code="caption_too_long",
            message=f"캡션이 {len(caption)}자입니다. 최대 140자.",
        )
    if not _KOREAN_RE.search(caption):
        raise CaptionValidationError(
            code="no_korean",
            message="캡션에 한국어가 없습니다.",
        )


async def validate_caption_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    check_caption(state["raw_caption"])
    return Command(goto="builder")
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_validate_caption.py -v
```
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/nodes/validate_caption.py tests/agents/feed_generation/test_node_validate_caption.py
git commit -m "feat(feed_generation): add validate_caption node"
```

---

### Task 10: builder 노드

**Files:**
- Create: `agents/feed_generation/nodes/builder.py`
- Test: `tests/agents/feed_generation/test_node_builder.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/agents/feed_generation/test_node_builder.py
from langgraph.constants import END
from agents.feed_generation.nodes.builder import builder_node
from agents.feed_generation.schemas import GeneratedFeed
from tests.agents.feed_generation.fakes import make_state


async def test_builder_node_constructs_generated_feed():
    state = make_state(
        image_url="https://s3.example.com/feeds/out.png",
        raw_caption="오늘 청소 완료 ✨",
    )
    cmd = await builder_node(state, {})

    assert cmd.goto == END
    feed: GeneratedFeed = cmd.update["result"]
    assert feed.character_id == state["input"].character.character_id
    assert feed.quest_id == state["input"].quest.quest_id
    assert feed.image_url == "https://s3.example.com/feeds/out.png"
    assert feed.caption == "오늘 청소 완료 ✨"


async def test_builder_node_result_is_generated_feed_instance():
    state = make_state(
        image_url="https://s3.example.com/feeds/out.png",
        raw_caption="청소 최고 ✨",
    )
    cmd = await builder_node(state, {})
    assert isinstance(cmd.update["result"], GeneratedFeed)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_builder.py -v
```
Expected: ImportError

- [ ] **Step 3: builder.py 구현**

```python
# agents/feed_generation/nodes/builder.py
from typing import Literal

from langgraph.constants import END
from langgraph.types import Command

from agents.feed_generation.schemas import GeneratedFeed
from agents.feed_generation.state import FeedGraphState

_Target = Literal["__end__"]


async def builder_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    result = GeneratedFeed(
        character_id=state["input"].character.character_id,
        quest_id=state["input"].quest.quest_id,
        image_url=state["image_url"],
        caption=state["raw_caption"],
    )
    return Command(update={"result": result}, goto=END)
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_node_builder.py -v
```
Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/nodes/builder.py tests/agents/feed_generation/test_node_builder.py
git commit -m "feat(feed_generation): add builder node"
```

---

### Task 11: Graph + Pipeline + debug

**Files:**
- Create: `agents/feed_generation/graph.py`
- Create: `agents/feed_generation/pipeline.py`
- Create: `agents/feed_generation/debug.py`

- [ ] **Step 1: graph.py 작성**

```python
# agents/feed_generation/graph.py
from langgraph.graph import END, START, StateGraph
from langgraph.pregel import RetryPolicy

from agents.feed_generation.exceptions import (
    CaptionGenerationError,
    ImageGenerationError,
    S3UploadError,
)
from agents.feed_generation.nodes import (
    assemble_caption_ctx,
    assemble_image_prompt,
    builder,
    img2img,
    llm_caption,
    s3_upload,
    validate,
    validate_caption,
)
from agents.feed_generation.state import FeedGraphState


def build_graph():
    graph = StateGraph(FeedGraphState)

    graph.add_node("validate", validate.validate_node)
    graph.add_node("assemble_image_prompt", assemble_image_prompt.assemble_image_prompt_node)
    graph.add_node(
        "img2img",
        img2img.img2img_node,
        retry=RetryPolicy(max_attempts=3, retry_on=ImageGenerationError),
    )
    graph.add_node(
        "s3_upload",
        s3_upload.s3_upload_node,
        retry=RetryPolicy(max_attempts=3, retry_on=S3UploadError),
    )
    graph.add_node("assemble_caption_ctx", assemble_caption_ctx.assemble_caption_ctx_node)
    graph.add_node(
        "llm_caption",
        llm_caption.llm_caption_node,
        retry=RetryPolicy(max_attempts=3, retry_on=CaptionGenerationError),
    )
    graph.add_node("validate_caption", validate_caption.validate_caption_node)
    graph.add_node("builder", builder.builder_node)

    graph.add_edge(START, "validate")

    return graph.compile()
```

- [ ] **Step 2: pipeline.py 작성**

```python
# agents/feed_generation/pipeline.py
from agents.feed_generation.graph import build_graph
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import FeedGenerationInput, GeneratedFeed

_graph = build_graph()


async def run(input: FeedGenerationInput, *, ports: Ports) -> GeneratedFeed:
    initial_state = {
        "input": input,
        "image_prompt": None,
        "raw_image": None,
        "image_url": None,
        "caption_ctx": None,
        "raw_caption": None,
        "result": None,
    }
    config = {"configurable": {"ports": ports}}

    final_state = initial_state
    async for event in _graph.astream(initial_state, config=config, stream_mode="values"):
        final_state = event

    return final_state["result"]
```

- [ ] **Step 3: debug.py 작성**

```python
# agents/feed_generation/debug.py
from agents.feed_generation.state import FeedGraphState


def print_state(state: FeedGraphState) -> None:
    print(f"  image_prompt : {(state.get('image_prompt') or '')[:80]}")
    print(f"  raw_image    : {len(state.get('raw_image') or b'')} bytes")
    print(f"  image_url    : {state.get('image_url')}")
    print(f"  caption_ctx  : {(state.get('caption_ctx') or '')[:80]}")
    print(f"  raw_caption  : {state.get('raw_caption')}")
    print(f"  result       : {state.get('result')}")
```

- [ ] **Step 4: graph import 검증**

```bash
uv run python -c "from agents.feed_generation.graph import build_graph; g = build_graph(); print('Graph OK')"
```
Expected: Graph OK

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/graph.py agents/feed_generation/pipeline.py agents/feed_generation/debug.py
git commit -m "feat(feed_generation): wire graph and pipeline"
```

---

### Task 12: 통합 테스트 (pipeline.run)

**Files:**
- Test: `tests/agents/feed_generation/test_pipeline.py`

- [ ] **Step 1: 통합 테스트 작성**

```python
# tests/agents/feed_generation/test_pipeline.py
import pytest
from agents.feed_generation import pipeline
from agents.feed_generation.exceptions import (
    CaptionValidationError,
    ImageGenerationError,
    S3UploadError,
)
from agents.feed_generation.schemas import GeneratedFeed
from tests.agents.feed_generation.fakes import (
    FakeLLM,
    FailingImageGenerator,
    FailingS3,
    make_input,
    make_ports,
)


async def test_pipeline_run_returns_generated_feed():
    inp = make_input()
    ports = make_ports()

    result = await pipeline.run(inp, ports=ports)

    assert isinstance(result, GeneratedFeed)
    assert result.character_id == inp.character.character_id
    assert result.quest_id == inp.quest.quest_id
    assert result.image_url.startswith("https://")
    assert len(result.caption) <= 140


async def test_pipeline_run_propagates_image_generation_error_after_retries():
    inp = make_input()
    ports = make_ports(image_generator=FailingImageGenerator())

    with pytest.raises(ImageGenerationError):
        await pipeline.run(inp, ports=ports)


async def test_pipeline_run_propagates_s3_upload_error_after_retries():
    inp = make_input()
    ports = make_ports(s3=FailingS3())

    with pytest.raises(S3UploadError):
        await pipeline.run(inp, ports=ports)


async def test_pipeline_run_propagates_caption_validation_error_for_non_korean():
    inp = make_input()
    ports = make_ports(llm=FakeLLM(caption="Cleaned my room! Great day!"))

    with pytest.raises(CaptionValidationError) as exc_info:
        await pipeline.run(inp, ports=ports)
    assert exc_info.value.code == "no_korean"


async def test_pipeline_run_propagates_caption_validation_error_for_too_long():
    inp = make_input()
    ports = make_ports(llm=FakeLLM(caption="가" * 141))

    with pytest.raises(CaptionValidationError) as exc_info:
        await pipeline.run(inp, ports=ports)
    assert exc_info.value.code == "caption_too_long"
```

- [ ] **Step 2: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/agents/feed_generation/test_pipeline.py -v
```
Expected: 5 passed

- [ ] **Step 3: 전체 feed_generation 테스트 실행**

```bash
uv run pytest tests/agents/feed_generation/ -v
```
Expected: 모두 통과

- [ ] **Step 4: 커밋**

```bash
git add tests/agents/feed_generation/test_pipeline.py
git commit -m "test(feed_generation): add integration tests for pipeline.run"
```

---

### Task 13: Mi:dm LLM 어댑터

**Files:**
- Create: `adapters/feed_generation/__init__.py`
- Create: `adapters/feed_generation/midm_llm.py`
- Test: `tests/adapters/feed_generation/test_midm_llm.py`

- [ ] **Step 1: 디렉토리 및 __init__ 생성**

```bash
mkdir -p adapters/feed_generation
mkdir -p tests/adapters/feed_generation
touch adapters/feed_generation/__init__.py
touch tests/adapters/feed_generation/__init__.py
```

- [ ] **Step 2: 실패하는 어댑터 테스트 작성**

```python
# tests/adapters/feed_generation/test_midm_llm.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from adapters.feed_generation.midm_llm import MidmLLM
from agents.feed_generation.exceptions import CaptionGenerationError


async def test_midm_llm_returns_stripped_text():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "  오늘 청소 완료 ✨  "

    with patch("adapters.feed_generation.midm_llm.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai.return_value = mock_client

        adapter = MidmLLM(model="midm-mini", base_url="http://localhost:8000/v1")
        result = await adapter.generate("테스트 프롬프트")

    assert result == "오늘 청소 완료 ✨"


async def test_midm_llm_raises_caption_generation_error_on_api_failure():
    with patch("adapters.feed_generation.midm_llm.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("연결 실패"))
        mock_openai.return_value = mock_client

        adapter = MidmLLM(model="midm-mini", base_url="http://localhost:8000/v1")
        with pytest.raises(CaptionGenerationError):
            await adapter.generate("프롬프트")


async def test_midm_llm_passes_prompt_as_user_message():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "한국어 캡션"

    with patch("adapters.feed_generation.midm_llm.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai.return_value = mock_client

        adapter = MidmLLM(model="midm-mini", base_url="http://localhost:8000/v1")
        await adapter.generate("내 프롬프트")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"][0]["role"] == "user"
        assert call_kwargs["messages"][0]["content"] == "내 프롬프트"
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/adapters/feed_generation/test_midm_llm.py -v
```
Expected: ImportError

- [ ] **Step 4: midm_llm.py 구현**

```python
# adapters/feed_generation/midm_llm.py
from dataclasses import dataclass

from openai import AsyncOpenAI

from agents.feed_generation.exceptions import CaptionGenerationError


@dataclass
class MidmLLM:
    model: str
    base_url: str
    api_key: str = "EMPTY"
    temperature: float = 0.7

    async def generate(self, prompt: str) -> str:
        client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            raise CaptionGenerationError(str(exc)) from exc
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/adapters/feed_generation/test_midm_llm.py -v
```
Expected: 3 passed

- [ ] **Step 6: 전체 테스트 실행**

```bash
uv run pytest tests/agents/feed_generation/ tests/adapters/feed_generation/ -v
```
Expected: 모두 통과

- [ ] **Step 7: 커밋**

```bash
git add adapters/feed_generation/ tests/adapters/feed_generation/
git commit -m "feat(feed_generation): add Mi:dm LLM adapter"
```
