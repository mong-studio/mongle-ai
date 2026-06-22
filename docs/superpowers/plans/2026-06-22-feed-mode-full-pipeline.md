# 피드 풀 파이프라인 (RunPod `feed` 모드) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hadimee `feed_pipeline` 5단계(캐릭터 img2img→누끼→배경→합성→inpaint 블렌딩)를 RunPod 워커 `feed` 모드로 이식하고, 피드 에이전트가 워커 1회 호출로 완성 이미지를 받도록 재구성한다.

**Architecture:** 5단계는 GPU가 필요하므로 RunPod 워커 안 `FeedMode`에서 in-process 수행(SDXL 1벌, `from_pipe`로 i2i·inpaint 공유). 에이전트 그래프는 `gen_feed_prompt(LLM)→feed_image→s3_upload→gen_caption_prompt→llm_caption→builder`로 단순화하고, 입력/출력 검증은 Pydantic 스키마로 이전한다.

**Tech Stack:** Python 3.12, LangGraph, Pydantic v2, diffusers(SDXL+LoRA+LCM), rembg, httpx, pytest/pytest-asyncio, RunPod Serverless.

**설계 스펙:** [`docs/superpowers/specs/2026-06-22-feed-mode-full-pipeline-design.md`](../specs/2026-06-22-feed-mode-full-pipeline-design.md)
**다이어그램:** [`docs/features/feed_generation/architecture-feed-mode.mmd`](../../features/feed_generation/architecture-feed-mode.mmd)
**참조 SSOT:** `~/Downloads/pipeline.py` (== Hadimee `mongle-bg-lora/feed_pipeline/pipeline.py`)

## Global Constraints

- **불변성:** 절대 mutate 금지. 항상 새 객체/`Command(update=...)` 반환. (글로벌 룰)
- **에러 처리:** 외부 호출(LLM/이미지/S3/HTTP)은 try/except로 도메인 예외로 변환해 전파.
- **테스트 커버리지:** 80%+ 유지. GPU 추론은 CI 불가 → import-smoke + 순수함수 CPU 테스트로 대체.
- **커밋:** conventional commits(`feat:`/`refactor:`/`test:`/`docs:`), 어트리뷰션 트레일러 없음(전역 비활성화).
- **파라미터 기본값(run.py SSOT, verbatim):** blend_mode=`inpaint`, inpaint_strength=`0.35`, character_strength=`0.75`, steps=`8`, char_scale=`1.0`, bg_scale=`1.0`(캐릭터 생성 시 bg_scale=`0.3` 오버라이드), character_seed=`42`, background_seed=랜덤.
- **모델 핀(기존 워커 verbatim):** base SDXL `stabilityai/stable-diffusion-xl-base-1.0` rev `462165984030d82259a11f4367a4eed129e94a7b`, LCM LoRA `latent-consistency/lcm-lora-sdxl` rev `a18548dd4956b174ec5b0d78d340c8dae0a129cd`.
- **캡션 제약:** 한국어 포함, ≤140자. quest ≤300자.
- **브랜치:** `feat/feed-mode-full-pipeline` (이미 생성됨, 설계 문서 커밋 완료).

> ⚠️ 워킹트리에 기존 WIP(미커밋)가 있다: `nodes/bg.py`, `nodes/composite.py`(untracked), 수정된 `pipeline.py`/`img2img.py`/`state.py`/`protocols.py`/`runpod_image.py`/`fakes.py`/`test_node_img2img.py`. 본 계획은 이 WIP를 **대체**한다(feed 모드가 bg+composite를 흡수). 각 태스크는 현재 워킹트리 파일 기준으로 작성됨.

---

### Task 1: 스키마 — 필드 개명 + 검증 이전 (alias 호환 창)

`validate`/`validate_caption` 노드의 검증을 스키마로 옮기고, `appearance_keywords→visual`·`quest_text→quest` 개명. **mongle-server 무중단 배포**를 위해 신·구 키를 둘 다 수용하는 `AliasChoices`를 둔다(추후 정리 태스크에서 구 키 제거).

**Files:**
- Modify: `agents/feed_generation/schemas.py`
- Test: `tests/agents/feed_generation/test_schemas.py` (Create)

**Interfaces:**
- Produces: `CharacterRef.visual: list[str]`, `CharacterRef.image_url: str`(min_length 1), `QuestRef.quest: str`, `GeneratedFeed.caption`(≤140 + 한글), 신규 `FeedPrompt` 모델 `{character: str, scene: str}`.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/agents/feed_generation/test_schemas.py
from uuid import uuid4
import pytest
from pydantic import ValidationError
from agents.feed_generation.schemas import CharacterRef, QuestRef, GeneratedFeed


def _char(**kw):
    data = dict(character_id=uuid4(), name="몽글이", personality="밝음",
                speech_style="반말", visual=["분홍"], image_url="https://x/y.png")
    data.update(kw)
    return data


def test_visual_alias_accepts_old_key():
    c = CharacterRef(**{k: v for k, v in _char().items() if k != "visual"},
                     appearance_keywords=["분홍"])
    assert c.visual == ["분홍"]


def test_quest_alias_accepts_old_key():
    q = QuestRef(quest_id=uuid4(), quest_text="방 청소하기")
    assert q.quest == "방 청소하기"


def test_blank_image_url_rejected():
    with pytest.raises(ValidationError):
        CharacterRef(**_char(image_url="   "))


def test_caption_requires_korean():
    with pytest.raises(ValidationError):
        GeneratedFeed(character_id=uuid4(), quest_id=uuid4(),
                      image_url="https://x", caption="all english here")


def test_caption_over_140_rejected():
    with pytest.raises(ValidationError):
        GeneratedFeed(character_id=uuid4(), quest_id=uuid4(),
                      image_url="https://x", caption="가" * 141)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd mongle-ai && uv run pytest tests/agents/feed_generation/test_schemas.py -v`
Expected: FAIL (ImportError/ValidationError 미발생 등)

- [ ] **Step 3: 스키마 구현**

```python
# agents/feed_generation/schemas.py
from __future__ import annotations
import re
from typing import Annotated
from uuid import UUID
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class QuestRef(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    quest_id: UUID
    quest: Annotated[str, Field(min_length=1, max_length=300,
                                validation_alias=AliasChoices("quest", "quest_text"))]


class CharacterRef(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True,
                              str_strip_whitespace=True)
    character_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=50)]
    personality: str
    speech_style: str
    visual: list[str] = Field(
        validation_alias=AliasChoices("visual", "appearance_keywords"))
    image_url: Annotated[str, Field(min_length=1)]


class FeedGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest: QuestRef
    character: CharacterRef


class FeedPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character: str  # visual + action (캐릭터 포즈)
    scene: str      # 배경 장면


class GeneratedFeed(BaseModel):
    character_id: UUID
    quest_id: UUID
    image_url: str
    caption: Annotated[str, Field(max_length=140)]

    @field_validator("caption")
    @classmethod
    def _must_contain_korean(cls, v: str) -> str:
        if not re.search(r"[가-힣]", v):
            raise ValueError("caption must contain Korean")
        return v
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd mongle-ai && uv run pytest tests/agents/feed_generation/test_schemas.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/schemas.py tests/agents/feed_generation/test_schemas.py
git commit -m "refactor(feed): 스키마로 입출력 검증 이전 + visual/quest 개명(alias 호환)"
```

---

### Task 2: state — `feed_prompt`/`caption_prompt`로 교체, `raw_bg` 제거

**Files:**
- Modify: `agents/feed_generation/state.py`

**Interfaces:**
- Consumes: `FeedPrompt`(Task 1).
- Produces: `FeedGraphState` 키 `feed_prompt: FeedPrompt | None`, `caption_prompt: str | None`. (`image_prompt`/`raw_bg`/`caption_ctx` 제거)

- [ ] **Step 1: state 갱신**

```python
# agents/feed_generation/state.py
from __future__ import annotations
from typing import TypedDict
from agents.feed_generation.schemas import FeedGenerationInput, FeedPrompt, GeneratedFeed


class FeedGraphState(TypedDict):
    input: FeedGenerationInput
    feed_prompt: FeedPrompt | None   # gen_feed_prompt 산출(character/scene)
    raw_image: bytes | None          # 워커 feed 모드 완성 PNG
    image_url: str | None
    caption_prompt: str | None       # gen_caption_prompt 산출
    raw_caption: str | None
    result: GeneratedFeed | None
```

- [ ] **Step 2: 컴파일 확인 (import-smoke)**

Run: `cd mongle-ai && uv run python -c "from agents.feed_generation.state import FeedGraphState; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 커밋**

```bash
git add agents/feed_generation/state.py
git commit -m "refactor(feed): state를 feed_prompt/caption_prompt로 교체, raw_bg 제거"
```

---

### Task 3: 포트 + 테스트 fakes — `generate_feed` 인터페이스

**Files:**
- Modify: `agents/feed_generation/protocols.py`
- Modify: `tests/agents/feed_generation/fakes.py`

**Interfaces:**
- Produces: `ImageGeneratorPort.generate_feed(reference_url: str, character_prompt: str, scene_prompt: str) -> bytes`; fakes: `FakeImageGenerator.generate_feed`(+`.feed_calls`), `ScriptedLLM(responses: list[str])`, `FailingLLM`, `make_state`/`make_ports` 갱신.

- [ ] **Step 1: 포트 교체**

```python
# agents/feed_generation/protocols.py — ImageGeneratorPort 만 교체
class ImageGeneratorPort(Protocol):
    async def generate_feed(
        self, reference_url: str, character_prompt: str, scene_prompt: str
    ) -> bytes: ...
```
(나머지 `LLMPort`/`S3Port`/`Ports` 는 그대로)

- [ ] **Step 2: fakes 갱신**

```python
# tests/agents/feed_generation/fakes.py — 교체/추가 부분

# make_input: appearance_keywords→visual, quest_text→quest
def make_input(**overrides):
    data = dict(
        quest=QuestRef(quest_id=uuid4(), quest="방 청소하기"),
        character=CharacterRef(
            character_id=uuid4(), name="몽글이", personality="밝고 활발함",
            speech_style="반말, 이모티콘 자주 사용",
            visual=["분홍색 머리", "큰 눈", "귀여운"],
            image_url="https://s3.example.com/characters/test.png",
        ),
    )
    data.update(overrides)
    return FeedGenerationInput(**data)


def make_state(**overrides):
    defaults = {
        "input": make_input(), "feed_prompt": None, "raw_image": None,
        "image_url": None, "caption_prompt": None, "raw_caption": None, "result": None,
    }
    defaults.update(overrides)
    return defaults


class FakeLLM:  # 단일 응답 (캡션 노드용)
    def __init__(self, response="오늘 방 청소 완료! 기분 최고 ✨"):
        self.response = response
        self.calls = []
    async def generate(self, prompt):
        self.calls.append(prompt)
        return self.response


class ScriptedLLM:  # 호출별 다른 응답 (파이프라인 통합 테스트용)
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    async def generate(self, prompt):
        self.calls.append(prompt)
        return self.responses.pop(0)


class FailingLLM:
    async def generate(self, prompt):
        raise RuntimeError("LLM 서버 오류")


class FakeImageGenerator:
    def __init__(self, image_bytes=_FAKE_BG_PNG):
        self.image_bytes = image_bytes
        self.feed_calls = []
    async def generate_feed(self, reference_url, character_prompt, scene_prompt):
        self.feed_calls.append((reference_url, character_prompt, scene_prompt))
        return self.image_bytes


class FailingImageGenerator:
    async def generate_feed(self, reference_url, character_prompt, scene_prompt):
        raise ImageGenerationError("이미지 생성 서버 오류")
```
(`make_ports` 의 `llm=FakeLLM()` 유지; `_FAKE_SPRITE_PNG`/`bg_calls`/구 `generate_img2img`·`generate_bg` 등 미사용분 제거. `_FAKE_BG_PNG` 헬퍼는 유지.)

- [ ] **Step 3: import-smoke**

Run: `cd mongle-ai && uv run python -c "from tests.agents.feed_generation import fakes; fakes.make_ports(); print('ok')"`
Expected: `ok`

- [ ] **Step 4: 커밋**

```bash
git add agents/feed_generation/protocols.py tests/agents/feed_generation/fakes.py
git commit -m "refactor(feed): ImageGeneratorPort.generate_feed + 테스트 fakes 갱신"
```

---

### Task 4: `gen_feed_prompt` 노드 — LLM action/scene 분해

**Files:**
- Create: `agents/feed_generation/nodes/gen_feed_prompt.py`
- Modify: `agents/feed_generation/exceptions.py` (PromptGenerationError 추가)
- Delete: `agents/feed_generation/nodes/assemble_image_prompt.py`, `tests/agents/feed_generation/test_node_assemble_image_prompt.py`
- Test: `tests/agents/feed_generation/test_node_gen_feed_prompt.py` (Create)

**Interfaces:**
- Consumes: `Ports.llm`, `FeedPrompt`, state `input`.
- Produces: `gen_feed_prompt_node` → `Command(update={"feed_prompt": FeedPrompt(...)}, goto="feed_image")`; `PromptGenerationError(FeedGenerationError)`.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/agents/feed_generation/test_node_gen_feed_prompt.py
import pytest
from agents.feed_generation.nodes.gen_feed_prompt import gen_feed_prompt_node
from agents.feed_generation.exceptions import PromptGenerationError
from tests.agents.feed_generation.fakes import make_state, make_ports, FakeLLM, FailingLLM

pytestmark = pytest.mark.asyncio


async def test_splits_action_and_scene_and_prepends_visual():
    llm = FakeLLM("action: cleaning a messy room\nscene: cozy sunny bedroom")
    state = make_state()
    cmd = await gen_feed_prompt_node(state, {"configurable": {"ports": make_ports(llm=llm)}})
    fp = cmd.update["feed_prompt"]
    assert "cleaning a messy room" in fp.character
    assert "분홍색 머리" in fp.character          # visual 결합
    assert fp.scene == "cozy sunny bedroom"
    assert cmd.goto == "feed_image"


async def test_missing_scene_falls_back_to_action():
    llm = FakeLLM("action: planting a tree")
    cmd = await gen_feed_prompt_node(make_state(), {"configurable": {"ports": make_ports(llm=llm)}})
    assert "planting a tree" in cmd.update["feed_prompt"].scene


async def test_llm_failure_raises_prompt_error():
    with pytest.raises(PromptGenerationError):
        await gen_feed_prompt_node(make_state(), {"configurable": {"ports": make_ports(llm=FailingLLM())}})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd mongle-ai && uv run pytest tests/agents/feed_generation/test_node_gen_feed_prompt.py -v`
Expected: FAIL (ModuleNotFoundError: gen_feed_prompt)

- [ ] **Step 3: 예외 + 노드 구현**

```python
# agents/feed_generation/exceptions.py — 추가
class PromptGenerationError(FeedGenerationError):
    """피드 프롬프트(action/scene) 생성 실패."""
```

```python
# agents/feed_generation/nodes/gen_feed_prompt.py
from typing import Any, Literal
from langgraph.types import Command
from agents.feed_generation.exceptions import PromptGenerationError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import CharacterRef, FeedPrompt, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["feed_image"]

_SYSTEM = (
    "You convert a Korean quest into two English lines for a pixel-art image.\n"
    "Output EXACTLY two lines:\n"
    "action: <6-12 word verb-starting phrase, the character performing the quest>\n"
    "scene: <short background scene description, no characters>\n"
    "Quest: {quest}"
)


def _parse(text: str) -> tuple[str, str]:
    action = scene = ""
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("action:"):
            action = line.split(":", 1)[1].strip()
        elif low.startswith("scene:"):
            scene = line.split(":", 1)[1].strip()
    action = action or scene
    scene = scene or action
    return action, scene


def _character_prompt(character: CharacterRef, action: str) -> str:
    visual = ", ".join(k for k in character.visual if k.strip())
    return f"{visual}, {action}" if visual else action


async def gen_feed_prompt_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    quest: QuestRef = state["input"].quest
    try:
        raw = await ports.llm.generate(_SYSTEM.format(quest=quest.quest))
    except Exception as exc:
        raise PromptGenerationError(str(exc)) from exc
    action, scene = _parse(raw)
    if not action:
        raise PromptGenerationError("LLM이 action/scene을 반환하지 않음")
    feed_prompt = FeedPrompt(
        character=_character_prompt(state["input"].character, action),
        scene=scene,
    )
    return Command(update={"feed_prompt": feed_prompt}, goto="feed_image")
```

- [ ] **Step 4: 테스트 통과 + 구 노드 삭제**

```bash
cd mongle-ai
uv run pytest tests/agents/feed_generation/test_node_gen_feed_prompt.py -v   # 3 passed
git rm agents/feed_generation/nodes/assemble_image_prompt.py \
       tests/agents/feed_generation/test_node_assemble_image_prompt.py
```

- [ ] **Step 5: 커밋**

```bash
git add agents/feed_generation/nodes/gen_feed_prompt.py \
        agents/feed_generation/exceptions.py \
        tests/agents/feed_generation/test_node_gen_feed_prompt.py
git commit -m "feat(feed): gen_feed_prompt 노드 — LLM action/scene 분해 + visual 결합"
```

---

### Task 5: `feed_image` 노드 — 워커 feed 1회 호출

**Files:**
- Create: `agents/feed_generation/nodes/feed_image.py`
- Delete: `agents/feed_generation/nodes/img2img.py`, `nodes/bg.py`, `nodes/composite.py` + 해당 테스트
- Test: `tests/agents/feed_generation/test_node_feed_image.py` (Create)

**Interfaces:**
- Consumes: `Ports.image_generator.generate_feed`, state `feed_prompt`, `input.character.image_url`.
- Produces: `feed_image_node` → `Command(update={"raw_image": bytes}, goto="s3_upload")`.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/agents/feed_generation/test_node_feed_image.py
import pytest
from agents.feed_generation.nodes.feed_image import feed_image_node
from agents.feed_generation.exceptions import ImageGenerationError
from agents.feed_generation.schemas import FeedPrompt
from tests.agents.feed_generation.fakes import (
    make_state, make_ports, FakeImageGenerator, FailingImageGenerator)

pytestmark = pytest.mark.asyncio


async def test_calls_generate_feed_with_prompts_and_ref():
    gen = FakeImageGenerator()
    state = make_state(feed_prompt=FeedPrompt(character="분홍, cleaning", scene="bedroom"))
    cmd = await feed_image_node(state, {"configurable": {"ports": make_ports(image_generator=gen)}})
    ref, char, scene = gen.feed_calls[0]
    assert ref == state["input"].character.image_url
    assert char == "분홍, cleaning" and scene == "bedroom"
    assert cmd.update["raw_image"] == gen.image_bytes
    assert cmd.goto == "s3_upload"


async def test_generator_failure_propagates():
    state = make_state(feed_prompt=FeedPrompt(character="x", scene="y"))
    with pytest.raises(ImageGenerationError):
        await feed_image_node(state, {"configurable": {"ports": make_ports(image_generator=FailingImageGenerator())}})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd mongle-ai && uv run pytest tests/agents/feed_generation/test_node_feed_image.py -v`
Expected: FAIL (ModuleNotFoundError: feed_image)

- [ ] **Step 3: 노드 구현**

```python
# agents/feed_generation/nodes/feed_image.py
from typing import Any, Literal
from langgraph.types import Command
from agents.feed_generation.exceptions import ImageGenerationError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.state import FeedGraphState

_Target = Literal["s3_upload"]


async def feed_image_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    feed_prompt = state["feed_prompt"]
    try:
        raw_image = await ports.image_generator.generate_feed(
            state["input"].character.image_url,
            feed_prompt.character,
            feed_prompt.scene,
        )
    except ImageGenerationError:
        raise
    except Exception as exc:
        raise ImageGenerationError(str(exc)) from exc
    return Command(update={"raw_image": raw_image}, goto="s3_upload")
```

- [ ] **Step 4: 테스트 통과 + 구 노드/테스트 삭제**

```bash
cd mongle-ai
uv run pytest tests/agents/feed_generation/test_node_feed_image.py -v   # 2 passed
git rm agents/feed_generation/nodes/img2img.py tests/agents/feed_generation/test_node_img2img.py
# bg.py/composite.py + 그 테스트는 untracked → 파일 삭제
rm -f agents/feed_generation/nodes/bg.py agents/feed_generation/nodes/composite.py \
      tests/agents/feed_generation/test_node_bg.py \
      tests/agents/feed_generation/test_node_composite.py
```

- [ ] **Step 5: 커밋**

```bash
git add -A agents/feed_generation/nodes tests/agents/feed_generation
git commit -m "feat(feed): feed_image 노드(워커 feed 1회 호출), 구 img2img/bg/composite 제거"
```

---

### Task 6: `gen_caption_prompt` 노드 — 개명 + feed_prompt 참조

**Files:**
- Create: `agents/feed_generation/nodes/gen_caption_prompt.py`
- Delete: `agents/feed_generation/nodes/assemble_caption_ctx.py`(+테스트 있으면)
- Modify: `agents/feed_generation/nodes/llm_caption.py` (입력 키 `caption_ctx→caption_prompt`, goto `validate_caption→builder`)
- Test: `tests/agents/feed_generation/test_node_gen_caption_prompt.py` (Create)

**Interfaces:**
- Consumes: state `input`, `feed_prompt`.
- Produces: `gen_caption_prompt_node` → `Command(update={"caption_prompt": str}, goto="llm_caption")`; `llm_caption_node` → `goto="builder"`.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/agents/feed_generation/test_node_gen_caption_prompt.py
import pytest
from agents.feed_generation.nodes.gen_caption_prompt import gen_caption_prompt_node
from agents.feed_generation.schemas import FeedPrompt
from tests.agents.feed_generation.fakes import make_state

pytestmark = pytest.mark.asyncio


async def test_builds_caption_prompt_with_persona_and_quest():
    state = make_state(feed_prompt=FeedPrompt(character="x", scene="bedroom"))
    cmd = await gen_caption_prompt_node(state, {})
    p = cmd.update["caption_prompt"]
    assert "몽글이" in p and "방 청소하기" in p
    assert cmd.goto == "llm_caption"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd mongle-ai && uv run pytest tests/agents/feed_generation/test_node_gen_caption_prompt.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: 노드 구현 + llm_caption 수정**

```python
# agents/feed_generation/nodes/gen_caption_prompt.py
from typing import Literal
from langgraph.types import Command
from agents.feed_generation.schemas import CharacterRef, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["llm_caption"]


def _build(character: CharacterRef, quest: QuestRef, scene: str) -> str:
    return (
        f"당신은 '{character.name}'이라는 캐릭터입니다.\n"
        f"성격: {character.personality}\n"
        f"말투: {character.speech_style}\n\n"
        f"방금 완료한 퀘스트: {quest.quest}\n"
        f"이미지 장면: {scene}\n\n"
        "위 퀘스트를 완료하고 느낀 소감을 캐릭터의 말투로 한국어 SNS 캡션으로 써주세요.\n"
        "규칙: 반드시 한국어로만 작성, 140자 이하, 캡션 텍스트만 출력"
    )


async def gen_caption_prompt_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    prompt = _build(state["input"].character, state["input"].quest,
                    state["feed_prompt"].scene)
    return Command(update={"caption_prompt": prompt}, goto="llm_caption")
```

```python
# agents/feed_generation/nodes/llm_caption.py — 3곳 수정
_Target = Literal["builder"]                       # was "validate_caption"
# ...
raw_caption = await ports.llm.generate(state["caption_prompt"])   # was state["caption_ctx"]
# ...
return Command(update={"raw_caption": raw_caption}, goto="builder")   # was "validate_caption"
```

- [ ] **Step 4: 테스트 통과 + 구 노드 삭제**

```bash
cd mongle-ai
uv run pytest tests/agents/feed_generation/test_node_gen_caption_prompt.py -v   # PASS
git rm agents/feed_generation/nodes/assemble_caption_ctx.py
rm -f tests/agents/feed_generation/test_node_assemble_caption_ctx.py
```

- [ ] **Step 5: 커밋**

```bash
git add -A agents/feed_generation/nodes tests/agents/feed_generation
git commit -m "refactor(feed): gen_caption_prompt 개명 + caption_prompt/builder 배선"
```

---

### Task 7: 에이전트 그래프 재구성 + validate 노드 제거

**Files:**
- Modify: `agents/feed_generation/pipeline.py`
- Delete: `nodes/validate.py`, `nodes/validate_caption.py` + 해당 테스트
- Test: `tests/agents/feed_generation/test_pipeline.py` (Modify)

**Interfaces:**
- Consumes: Task 4·5·6 노드들, `Ports`.
- Produces: `run(feed_input, *, ports) -> GeneratedFeed` (그래프 `gen_feed_prompt→feed_image→s3_upload→gen_caption_prompt→llm_caption→builder`).

- [ ] **Step 1: 파이프라인 통합 테스트 작성(해피패스)**

```python
# tests/agents/feed_generation/test_pipeline.py — 핵심 테스트 교체
import pytest
from agents.feed_generation.pipeline import run
from tests.agents.feed_generation.fakes import make_input, make_ports, ScriptedLLM, FakeImageGenerator

pytestmark = pytest.mark.asyncio


async def test_run_happy_path_produces_feed():
    # 1st LLM call = gen_feed_prompt(action/scene), 2nd = caption
    llm = ScriptedLLM(["action: cleaning a room\nscene: cozy bedroom",
                       "방 청소 끝! 뿌듯해 ✨"])
    ports = make_ports(llm=llm, image_generator=FakeImageGenerator())
    feed = await run(make_input(), ports=ports)
    assert feed.caption == "방 청소 끝! 뿌듯해 ✨"
    assert feed.image_url.startswith("https://")
    assert len(llm.calls) == 2
```
(기존 `validate`/`validate_caption`/구 노드 관련 케이스는 삭제)

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd mongle-ai && uv run pytest tests/agents/feed_generation/test_pipeline.py::test_run_happy_path_produces_feed -v`
Expected: FAIL (그래프가 구 노드 참조)

- [ ] **Step 3: 그래프 재작성**

```python
# agents/feed_generation/pipeline.py — build_graph 와 initial_state 교체
from langgraph.graph import END, START, StateGraph
from langgraph.pregel import RetryPolicy
from agents.feed_generation.exceptions import (
    CaptionGenerationError, FeedGenerationError, ImageGenerationError,
    PromptGenerationError, S3UploadError)
from agents.feed_generation.nodes import (
    builder, feed_image, gen_caption_prompt, gen_feed_prompt, llm_caption, s3_upload)
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import FeedGenerationInput, GeneratedFeed
from agents.feed_generation.state import FeedGraphState


def build_graph():
    g = StateGraph(FeedGraphState)
    g.add_node("gen_feed_prompt", gen_feed_prompt.gen_feed_prompt_node,
               retry=RetryPolicy(max_attempts=3, retry_on=PromptGenerationError))
    g.add_node("feed_image", feed_image.feed_image_node,
               retry=RetryPolicy(max_attempts=3, retry_on=ImageGenerationError))
    g.add_node("s3_upload", s3_upload.s3_upload_node,
               retry=RetryPolicy(max_attempts=3, retry_on=S3UploadError))
    g.add_node("gen_caption_prompt", gen_caption_prompt.gen_caption_prompt_node)
    g.add_node("llm_caption", llm_caption.llm_caption_node,
               retry=RetryPolicy(max_attempts=3, retry_on=CaptionGenerationError))
    g.add_node("builder", builder.builder_node)

    g.add_edge(START, "gen_feed_prompt")
    g.add_edge("gen_feed_prompt", "feed_image")
    g.add_edge("feed_image", "s3_upload")
    g.add_edge("s3_upload", "gen_caption_prompt")
    g.add_edge("gen_caption_prompt", "llm_caption")
    g.add_edge("llm_caption", "builder")
    g.add_edge("builder", END)
    return g.compile()


_graph = build_graph()


async def run(feed_input: FeedGenerationInput, *, ports: Ports) -> GeneratedFeed:
    initial_state = {
        "input": feed_input, "feed_prompt": None, "raw_image": None,
        "image_url": None, "caption_prompt": None, "raw_caption": None, "result": None,
    }
    final_state = await _graph.ainvoke(initial_state, config={"configurable": {"ports": ports}})
    result = final_state.get("result")
    if result is None:
        raise FeedGenerationError("Pipeline completed without producing a result")
    return result
```

- [ ] **Step 4: builder가 caption 검증 스키마를 타는지 확인**

`builder.builder_node` 가 `GeneratedFeed(...)` 를 생성하면 Task 1의 caption 검증(≤140·한글)이 자동 적용된다. builder 소스를 확인해 `caption=state["raw_caption"]` 로 GeneratedFeed 를 생성하는지 점검(아니면 맞춘다).

Run: `cd mongle-ai && uv run python -c "from agents.feed_generation.nodes import builder; import inspect; print(inspect.getsource(builder.builder_node))"`
Expected: GeneratedFeed 생성 코드 확인

- [ ] **Step 5: 구 노드/테스트 삭제 + feed_generation 전체 테스트**

```bash
cd mongle-ai
git rm agents/feed_generation/nodes/validate.py agents/feed_generation/nodes/validate_caption.py \
       tests/agents/feed_generation/test_node_validate.py \
       tests/agents/feed_generation/test_node_validate_caption.py
uv run pytest tests/agents/feed_generation/ -v
```
Expected: 전체 PASS (구 노드 잔존 참조 없음)

- [ ] **Step 6: 커밋**

```bash
git add -A agents/feed_generation tests/agents/feed_generation
git commit -m "feat(feed): 그래프 재구성(gen_feed_prompt→feed_image→...→builder), validate 노드 제거"
```

---

### Task 8: `RunPodImageGenerator.generate_feed` + `scene_prompt` payload

**Files:**
- Modify: `adapters/character_creation/runpod_image.py`
- Test: `tests/adapters/feed_generation/test_runpod_generate_feed.py` (Create)

**Interfaces:**
- Consumes: 워커 `/run` 계약(`input.adapter`, `source_image_b64`, `prompt`, `scene_prompt`).
- Produces: `RunPodImageGenerator.generate_feed(reference_url, character_prompt, scene_prompt) -> bytes`; `_submit_and_poll(..., *, adapter="character", scene_prompt=None)`.

- [ ] **Step 1: 실패 테스트 작성 (httpx MockTransport)**

```python
# tests/adapters/feed_generation/test_runpod_generate_feed.py
import base64, json, httpx, pytest
from adapters.character_creation.runpod_image import RunPodImageGenerator

pytestmark = pytest.mark.asyncio


async def test_generate_feed_sends_adapter_feed_and_scene_prompt():
    captured = {}
    png = base64.b64encode(b"\x89PNG\r\n").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith("/run"):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "job1"})
        if "/status/" in p:
            return httpx.Response(200, json={"status": "COMPLETED", "output": {"image_b64": png}})
        if "/ref" in p:                       # reference 이미지 다운로드
            return httpx.Response(200, content=b"refimg")
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gen = RunPodImageGenerator(endpoint_url="http://ep", api_key="k",
                               poll_interval=0, client=client)
    out = await gen.generate_feed("http://ep/ref/x.png", "분홍, cleaning", "cozy bedroom")
    assert out == b"\x89PNG\r\n"
    inp = captured["body"]["input"]
    assert inp["adapter"] == "feed"
    assert inp["prompt"] == "분홍, cleaning"
    assert inp["scene_prompt"] == "cozy bedroom"
    assert inp["source_image_b64"] == base64.b64encode(b"refimg").decode()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd mongle-ai && uv run pytest tests/adapters/feed_generation/test_runpod_generate_feed.py -v`
Expected: FAIL (generate_feed 없음)

- [ ] **Step 3: 구현**

```python
# adapters/character_creation/runpod_image.py
# (1) 구 generate_img2img / generate_bg 제거, generate_feed 추가:

    async def generate_feed(
        self, reference_url: str, character_prompt: str, scene_prompt: str
    ) -> bytes:
        """피드: reference 이미지 기반 5단계 feed 모드(adapter='feed')."""
        client = self._client or httpx.AsyncClient()
        owns = self._client is None
        try:
            resp = await client.get(reference_url, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            source_bytes = resp.content
        finally:
            if owns:
                await client.aclose()
        try:
            return await self._submit_and_poll(
                source_bytes, character_prompt, adapter="feed", scene_prompt=scene_prompt)
        except ImageGenerationFailedError:
            raise
        except Exception as err:
            raise ImageGenerationFailedError(f"[ERROR] RunPod feed 생성 실패: {err}") from err

# (2) _submit_and_poll 시그니처/payload 확장:
    async def _submit_and_poll(
        self, source_image_bytes, prompt, *, adapter="character", scene_prompt=None
    ) -> bytes:
        source_b64 = base64.b64encode(source_image_bytes).decode() if source_image_bytes else None
        payload = {"input": {"source_image_b64": source_b64, "adapter": adapter,
                             "prompt": prompt, "scene_prompt": scene_prompt}}
        # ... 이하 기존 폴링 로직(headers/run/status/cancel) 그대로 ...
```
> `generate(...)`(캐릭터 생성)는 `_submit_and_poll(source, prompt)` 호출이라 기본 `adapter="character"`, `scene_prompt=None` 로 동작 — 변경 없음.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd mongle-ai && uv run pytest tests/adapters/feed_generation/test_runpod_generate_feed.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add adapters/character_creation/runpod_image.py tests/adapters/feed_generation/test_runpod_generate_feed.py
git commit -m "feat(feed): RunPodImageGenerator.generate_feed + scene_prompt payload"
```

---

### Task 9: 워커 `handler.py` — `scene_prompt` 파싱

**Files:**
- Modify: `runpod_workers/image_gen/handler.py`
- Test: `tests/runpod_workers/test_handler_input.py` (Create; `tests/runpod_workers/__init__.py` 없으면 생성)

**Interfaces:**
- Produces: handler 가 `scene_prompt` 를 `get_pipeline().generate(...)` 로 전달; adapter 누락 시 ValueError.

- [ ] **Step 1: 실패 테스트 작성 (pipeline/runpod 모킹)**

```python
# tests/runpod_workers/test_handler_input.py
import base64, sys, types, importlib, pytest


def _load_handler(monkeypatch, capture):
    fake = types.ModuleType("pipeline")
    class _P:
        def generate(self, *, adapter, source_image_bytes, prompt, scene_prompt):
            capture.update(adapter=adapter, prompt=prompt, scene_prompt=scene_prompt,
                           has_src=source_image_bytes is not None)
            return b"PNG"
    fake.get_pipeline = lambda: _P()
    monkeypatch.setitem(sys.modules, "pipeline", fake)
    monkeypatch.setitem(sys.modules, "runpod", types.SimpleNamespace(
        serverless=types.SimpleNamespace(start=lambda *_a, **_k: None)))
    sys.path.insert(0, "runpod_workers/image_gen")
    return importlib.reload(importlib.import_module("handler"))


def test_handler_passes_scene_prompt(monkeypatch):
    cap = {}
    h = _load_handler(monkeypatch, cap)
    out = h.handler({"input": {"adapter": "feed", "prompt": "char", "scene_prompt": "bg",
                               "source_image_b64": base64.b64encode(b"x").decode()}})
    assert base64.b64decode(out["image_b64"]) == b"PNG"
    assert cap == {"adapter": "feed", "prompt": "char", "scene_prompt": "bg", "has_src": True}


def test_handler_requires_adapter(monkeypatch):
    h = _load_handler(monkeypatch, {})
    with pytest.raises(ValueError):
        h.handler({"input": {"prompt": "x"}})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd mongle-ai && uv run pytest tests/runpod_workers/test_handler_input.py -v`
Expected: FAIL (generate 가 scene_prompt 인자 안 받음)

- [ ] **Step 3: 구현**

```python
# runpod_workers/image_gen/handler.py — handler 본문 교체
def handler(job: dict) -> dict:
    job_input = job.get("input") or {}
    adapter = job_input.get("adapter")
    if not adapter or not isinstance(adapter, str):
        raise ValueError("[ERROR] 'adapter' 필드가 필요합니다 (character|bg|feed)")
    source_b64 = job_input.get("source_image_b64")
    source_bytes = base64.b64decode(source_b64, validate=True) if source_b64 else None
    png_bytes = get_pipeline().generate(
        adapter=adapter,
        source_image_bytes=source_bytes,
        prompt=job_input.get("prompt"),
        scene_prompt=job_input.get("scene_prompt"),
    )
    return {"image_b64": base64.b64encode(png_bytes).decode()}
```
(docstring 입력 예시에 `"feed"` 와 `scene_prompt` 추가)

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd mongle-ai && uv run pytest tests/runpod_workers/test_handler_input.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add runpod_workers/image_gen/handler.py tests/runpod_workers/
git commit -m "feat(feed): 워커 handler scene_prompt 파싱 + feed adapter"
```

---

### Task 10: 워커 `pipeline.py` — feed 등록 + lazy-load + `scene_prompt` 전달

**Files:**
- Modify: `runpod_workers/image_gen/pipeline.py`, `runpod_workers/image_gen/character_mode.py`, `runpod_workers/image_gen/bg_mode.py`
- Test: `tests/runpod_workers/test_pipeline_routing.py` (Create)

**Interfaces:**
- Consumes: `_ADAPTER_ENV`, 모드 클래스(character/bg/feed).
- Produces: `MultiAdapterImagePipeline.generate(*, adapter, source_image_bytes=None, prompt=None, scene_prompt=None)`; feed 는 char+bg env 둘 다 있을 때 사용 가능; 모드 lazy-load.

- [ ] **Step 1: 실패 테스트 작성 (모드 클래스 모킹)**

```python
# tests/runpod_workers/test_pipeline_routing.py
import sys, types, importlib, pytest


def _load_pipeline(monkeypatch, env):
    for k in ("LORA_CHARACTER_REPO", "LORA_BG_REPO"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for name, attr in [("character_mode", "CharacterMode"),
                       ("bg_mode", "BgMode"), ("feed_mode", "FeedMode")]:
        mod = types.ModuleType(name)
        def _make(label):
            class _M:
                def __init__(self, **kw): self.label = label
                def generate(self, *, source_image_bytes=None, prompt=None, scene_prompt=None):
                    return f"{label}:{prompt}:{scene_prompt}".encode()
            return _M
        setattr(mod, attr, _make(name))
        monkeypatch.setitem(sys.modules, name, mod)
    sys.path.insert(0, "runpod_workers/image_gen")
    return importlib.reload(importlib.import_module("pipeline"))


def test_feed_registered_when_both_loras_present(monkeypatch):
    p = _load_pipeline(monkeypatch, {"LORA_CHARACTER_REPO": "c", "LORA_BG_REPO": "b"})
    out = p.get_pipeline().generate(adapter="feed", prompt="char", scene_prompt="bg")
    assert out == b"feed_mode:char:bg"


def test_feed_unavailable_without_bg(monkeypatch):
    p = _load_pipeline(monkeypatch, {"LORA_CHARACTER_REPO": "c"})
    with pytest.raises(ValueError):
        p.get_pipeline().generate(adapter="feed", prompt="x", scene_prompt="y")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd mongle-ai && uv run pytest tests/runpod_workers/test_pipeline_routing.py -v`
Expected: FAIL (feed 미등록 / scene_prompt 미지원)

- [ ] **Step 3: 구현**

```python
# runpod_workers/image_gen/pipeline.py
from __future__ import annotations
import os

_ADAPTER_ENV = {"character": "LORA_CHARACTER_REPO", "bg": "LORA_BG_REPO"}


class MultiAdapterImagePipeline:
    """등록 가능한 어댑터를 lazy-load 하고 요청을 분기한다."""

    def __init__(self, *, adapters: dict[str, str]) -> None:
        self._adapters = adapters          # 이름 → LoRA repo
        self._modes: dict[str, object] = {}  # lazy 캐시

    def _available(self) -> set[str]:
        names = set(self._adapters)
        if "character" in self._adapters and "bg" in self._adapters:
            names.add("feed")
        return names

    def _load(self, adapter: str):
        if adapter == "character":
            from character_mode import CharacterMode
            return CharacterMode(lora_source=self._adapters["character"])
        if adapter == "bg":
            from bg_mode import BgMode
            return BgMode(lora_source=self._adapters["bg"])
        if adapter == "feed":
            from feed_mode import FeedMode
            return FeedMode(lora_character_source=self._adapters["character"],
                            lora_bg_source=self._adapters["bg"])
        raise ValueError(f"[ERROR] 알 수 없는 adapter: {adapter!r}")

    def generate(self, *, adapter, source_image_bytes=None, prompt=None, scene_prompt=None) -> bytes:
        if adapter not in self._available():
            raise ValueError(
                f"[ERROR] 알 수 없는 adapter: {adapter!r} "
                f"(이 엔드포인트: {sorted(self._available())})")
        mode = self._modes.get(adapter) or self._modes.setdefault(adapter, self._load(adapter))
        return mode.generate(source_image_bytes=source_image_bytes,
                             prompt=prompt, scene_prompt=scene_prompt)


_pipeline: MultiAdapterImagePipeline | None = None


def get_pipeline() -> MultiAdapterImagePipeline:
    global _pipeline
    if _pipeline is None:
        adapters = {name: repo for name, env in _ADAPTER_ENV.items()
                    if (repo := os.environ.get(env, "").strip())}
        if not adapters:
            raise RuntimeError(
                f"[ERROR] LoRA repo 환경변수가 최소 1개 필요합니다: {', '.join(_ADAPTER_ENV.values())}")
        _pipeline = MultiAdapterImagePipeline(adapters=adapters)
    return _pipeline
```
character/bg 모드 `generate` 시그니처에 `scene_prompt=None` 추가(무시):
```python
# character_mode.py / bg_mode.py
    def generate(self, *, source_image_bytes=None, prompt=None, scene_prompt=None) -> bytes:
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd mongle-ai && uv run pytest tests/runpod_workers/test_pipeline_routing.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add runpod_workers/image_gen/pipeline.py runpod_workers/image_gen/character_mode.py \
        runpod_workers/image_gen/bg_mode.py tests/runpod_workers/test_pipeline_routing.py
git commit -m "feat(feed): 워커 feed 어댑터 등록 + 모드 lazy-load + scene_prompt 전달"
```

---

### Task 11: 워커 `feed_mode.py` — 5단계 이식

`~/Downloads/pipeline.py`(= Hadimee `feed_pipeline/pipeline.py`)의 모듈 함수를 verbatim 복사하고 `FeedMode` 클래스로 감싼다. GPU 추론은 CI 불가 → 순수함수(composite/`_appearance_to_str`) CPU 테스트 + import-smoke 로 검증.

**Files:**
- Create: `runpod_workers/image_gen/feed_mode.py`
- Test: `tests/runpod_workers/test_feed_mode_composite.py` (Create)

**Interfaces:**
- Consumes: diffusers 파이프라인(런타임), `LORA_CHARACTER_REPO`/`LORA_BG_REPO`.
- Produces: `FeedMode(*, lora_character_source, lora_bg_source)`, `.generate(*, source_image_bytes, prompt, scene_prompt) -> bytes`; 테스트용 순수함수 `_composite_bytes(bg_bytes, sprite_bytes) -> (rgb_png, mask_png)`, `_appearance_to_str(dict) -> str`.

- [ ] **Step 1: 순수함수 CPU 테스트 작성**

```python
# tests/runpod_workers/test_feed_mode_composite.py
import io, sys
from PIL import Image
sys.path.insert(0, "runpod_workers/image_gen")


def _png(mode, color, size=(64, 64)):
    b = io.BytesIO(); Image.new(mode, size, color).save(b, "PNG"); return b.getvalue()


def test_composite_returns_rgb_and_mask_same_size():
    from feed_mode import _composite_bytes
    rgb, mask = _composite_bytes(_png("RGB", (0, 0, 255)), _png("RGBA", (255, 0, 0, 200)))
    r = Image.open(io.BytesIO(rgb)); m = Image.open(io.BytesIO(mask))
    assert r.mode == "RGB" and r.size == (64, 64)
    assert m.size == (64, 64)


def test_appearance_to_str_joins_fields():
    from feed_mode import _appearance_to_str
    s = _appearance_to_str({"body_color": "pink", "accessories": ["hat"]})
    assert "pink" in s and "hat" in s
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd mongle-ai && uv run pytest tests/runpod_workers/test_feed_mode_composite.py -v`
Expected: FAIL (feed_mode 없음)

- [ ] **Step 3: feed_mode.py 작성**

3-1. 상단: `from __future__ import annotations` + `import gc, io, os` + `import numpy as np` + `os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"]="1"`. **torch/diffusers/PIL/rembg 는 모듈 레벨 import 금지**(함수 내부 지연 import — 순수함수 테스트가 무거운 import 없이 통과해야 함).

3-2. `~/Downloads/pipeline.py` 에서 다음을 **verbatim 복사**(단 `CHARACTER_LORA`/`BG_LORA`/`LCM_LORA` 상수는 삭제 — env 주입으로 대체): `NEGATIVE`, `NEGATIVE_BG`, `BG_STYLE`, `_appearance_to_str`, `generate_character`, `remove_bg`, `generate_background`, `composite`, `inpaint_blend`, `img2img_blend`. (각 함수는 `import torch`/`from PIL import ...` 를 함수 내부에 이미 갖고 있음 — 그대로 유지.)

3-3. 테스트용 bytes 래퍼 추가:
```python
def _composite_bytes(bg_bytes: bytes, sprite_bytes: bytes):
    from PIL import Image
    bg = Image.open(io.BytesIO(bg_bytes)).convert("RGB")
    sprite = Image.open(io.BytesIO(sprite_bytes)).convert("RGBA")
    rgb, mask = composite(bg, sprite)            # 원본 composite(bg_pil, char_nobg_pil)
    rb, mb = io.BytesIO(), io.BytesIO()
    rgb.save(rb, "PNG"); mask.save(mb, "PNG")
    return rb.getvalue(), mb.getvalue()
```

3-4. `FeedMode` 클래스:
```python
class FeedMode:
    """SDXL + char/bg/lcm LoRA + i2i/inpaint(from_pipe). run.py 기본값 bake."""
    _BLEND_MODE = "inpaint"   # 토글: "inpaint" | "img2img"
    _STRENGTH = 0.75
    _INPAINT_STR = 0.35
    _STEPS = 8
    _CHAR_SCALE = 1.0
    _CHAR_SEED = 42

    def __init__(self, *, lora_character_source: str, lora_bg_source: str) -> None:
        import torch
        from diffusers import (LCMScheduler, StableDiffusionXLImg2ImgPipeline,
                               StableDiffusionXLInpaintPipeline, StableDiffusionXLPipeline)
        t2i = StableDiffusionXLPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0",
            revision="462165984030d82259a11f4367a4eed129e94a7b",
            torch_dtype=torch.float16, use_safetensors=True, variant="fp16").to("cuda")
        t2i.load_lora_weights(lora_character_source, adapter_name="character")
        t2i.load_lora_weights(lora_bg_source, adapter_name="bg")
        t2i.load_lora_weights("latent-consistency/lcm-lora-sdxl", adapter_name="lcm",
                              revision="a18548dd4956b174ec5b0d78d340c8dae0a129cd")
        t2i.scheduler = LCMScheduler.from_config(t2i.scheduler.config)
        t2i.enable_attention_slicing()
        self._t2i = t2i
        self._i2i = StableDiffusionXLImg2ImgPipeline.from_pipe(t2i)
        self._inpaint = StableDiffusionXLInpaintPipeline.from_pipe(t2i)

    def generate(self, *, source_image_bytes: bytes | None = None,
                 prompt: str | None = None, scene_prompt: str | None = None) -> bytes:
        from PIL import Image
        if source_image_bytes is None:
            raise ValueError("[ERROR] feed 모드는 source_image_bytes(캐릭터 기준 이미지)가 필요합니다")
        if not (prompt and prompt.strip()):
            raise ValueError("[ERROR] feed 모드는 prompt(캐릭터 포즈)가 필요합니다")
        scene = (scene_prompt or prompt).strip()
        char_src = Image.open(io.BytesIO(source_image_bytes)).convert("RGBA")
        char = generate_character(self._i2i, char_src, prompt,
                                  char_scale=self._CHAR_SCALE, bg_scale=0.3,
                                  strength=self._STRENGTH, steps=self._STEPS, seed=self._CHAR_SEED)
        char_nobg = remove_bg(char)
        bg = generate_background(self._t2i, scene, steps=self._STEPS, seed=None)
        comp_rgb, mask_rgb = composite(bg, char_nobg)
        if self._BLEND_MODE == "img2img":
            final = img2img_blend(self._i2i, comp_rgb, prompt, steps=self._STEPS)
        else:
            final = inpaint_blend(self._inpaint, comp_rgb, mask_rgb, prompt,
                                  strength=self._INPAINT_STR, steps=self._STEPS)
        buf = io.BytesIO(); final.convert("RGB").save(buf, "PNG"); return buf.getvalue()
```

- [ ] **Step 4: 순수함수 테스트 통과 확인**

Run: `cd mongle-ai && uv run pytest tests/runpod_workers/test_feed_mode_composite.py -v`
Expected: PASS (2 passed)
> 모듈 import 시 torch/diffusers 가 모듈 레벨에 없어야 통과(지연 import 확인). reference 가 모듈 레벨에서 numpy 만 import → OK.

- [ ] **Step 5: GPU 박스 import-smoke (선택, 머지 전)**

CUDA dev/RunPod 환경에서:
Run: `LORA_CHARACTER_REPO=Hadimeeee/mongle-character-lora LORA_BG_REPO=Hadimeeee/mongle-bg-lora python -c "import sys; sys.path.insert(0,'runpod_workers/image_gen'); from feed_mode import FeedMode; print('import ok')"`
Expected: `import ok` (CI에선 skip)

- [ ] **Step 6: 커밋**

```bash
git add runpod_workers/image_gen/feed_mode.py tests/runpod_workers/test_feed_mode_composite.py
git commit -m "feat(feed): 워커 feed_mode 5단계 이식(Hadimee feed_pipeline)"
```

---

### Task 12: 통합 검증 + CHANGELOG + 다이어그램 as-built

**Files:**
- Modify: `CHANGELOG.md`, `docs/features/feed_generation/architecture.mmd`(as-built 갱신)

- [ ] **Step 1: 전체 테스트 + 커버리지**

Run: `cd mongle-ai && uv run pytest tests/ -q --cov=agents/feed_generation --cov=adapters/character_creation/runpod_image --cov-report=term-missing`
Expected: 전체 PASS, feed_generation 커버리지 80%+

- [ ] **Step 2: CHANGELOG 추가**

`CHANGELOG.md` 에 항목 추가: feed 풀 파이프라인(워커 feed 모드 + 에이전트 재구성 + 스키마 개명).

- [ ] **Step 3: as-built 다이어그램 동기화**

`architecture.mmd`(현행)를 `architecture-feed-mode.mmd` 내용으로 갱신(피처 완성 = as-built 신 설계). DoD: `docs/FEATURES.md` §4.

- [ ] **Step 4: 커밋**

```bash
git add CHANGELOG.md docs/features/feed_generation/architecture.mmd
git commit -m "docs(feed): CHANGELOG + as-built 아키텍처 갱신"
```

---

## 배포 (구현 후, 별도 진행)

스펙 §5 순서: ① 워커 재배포(feed 등록, 하위호환) → ② mongle-ai 배포(generate_feed/그래프/스키마 alias) → ③ mongle-server payload 키 `visual`/`quest` 전환. mongle-ai 가 alias 로 신·구 키 모두 수용하므로 ②와 ③의 순서 결합이 강제되지 않음. 안정화 후 후속 태스크에서 구 키 alias 제거.

## 범위 밖 (follow-up)

- local provider(`LoRAImageGenerator`) feed 패리티 — 5단계 로직 공용 모듈 추출 필요 시.
- mongle-server payload 변경 — 별도 레포/플랜.
- 스키마 alias(`appearance_keywords`/`quest_text`) 제거 정리.
