# 피드 생성 풀 파이프라인 (RunPod `feed` 모드) 설계

- 날짜: 2026-06-22
- 상태: 설계 확정 (구현 계획 대기)
- 아키텍처 다이어그램: [`docs/features/feed_generation/architecture-feed-mode.mmd`](../../features/feed_generation/architecture-feed-mode.mmd) (PNG 동봉)
- 기존 피드 에이전트 설계: [`2026-05-27-feed-generation-design.md`](./2026-05-27-feed-generation-design.md)

---

## 1. 배경 / 문제

현재 배포된(`main`) 피드 파이프라인은 그래프가 `… → img2img → s3_upload → …` 로 직결되어 **정면 캐릭터 생성용 스프라이트 한 장만** 피드 이미지로 올라간다. 배경·합성·블렌딩이 없다.

워킹트리에 `bg.py`·`composite.py`(미커밋)가 있지만:
- 캐릭터를 퀘스트 동작 포즈로 만들지 않고, 캐릭터 **생성기(front view)** 를 그대로 재사용한다.
- 합성이 그림자·경계 봉합 없는 단순 알파 붙이기다.
- 블렌딩(STEP 5)이 아예 없다.

목표는 **Hadimee `mongle-bg-lora` 레포의 `feed_pipeline/` (pipeline.py + run.py)** 5단계를 충실히 이식해, "캐릭터가 퀘스트를 수행하는 한 장면" 피드 이미지를 생성하는 것이다.

### 참조 SSOT
- `Hadimeeee/mongle-bg-lora` → `feed_pipeline/pipeline.py` (단계 함수), `feed_pipeline/run.py` (오케스트레이션·기본 파라미터)
- 사용자가 제공한 `~/Downloads/pipeline.py` == `feed_pipeline/pipeline.py`

---

## 2. 아키텍처 결정

STEP 5 블렌딩은 SDXL inpaint(GPU)라 에이전트(CPU) 노드로 불가능. 따라서 **5단계 전체를 RunPod 워커 안 `feed` 모드로 in-process 수행**한다(reference 구조와 동일, `from_pipe`로 UNet 공유 → SDXL 1벌). 에이전트는 워커를 1회 호출하고 완성 이미지를 받는다.

(기각안: 단계를 워커/에이전트로 쪼개고 블렌딩만 워커를 한 번 더 호출 → 워커 왕복 3회 + 마스크 네트워크 전송 + 캐릭터 생성기와 adapter 충돌 위험. 채택안이 더 단순하고 reference에 충실.)

---

## 3. 워커 변경 (`runpod_workers/image_gen/`)

### 3.1 신규 `feed_mode.py` — `FeedMode`
`feed_pipeline/pipeline.py` 이식. 한 SDXL에 char+bg+lcm LoRA를 named adapter로 올리고 `from_pipe`로 i2i·inpaint 파이프 공유.

- `__init__(*, lora_character_source, lora_bg_source)` ← env 두 개 주입
- `generate(*, source_image_bytes, prompt, scene_prompt) -> bytes`:
  1. STEP1 `generate_character` (i2i) — `prompt`=캐릭터 포즈(visual+action), strength 0.75, bg_scale 0.3 오버라이드
  2. STEP2 `remove_bg` (rembg)
  3. STEP3 `generate_background` (t2i) — `scene_prompt`, 랜덤 seed
  4. STEP4 `composite` — 그림자 + rim 마스크
  5. STEP5 `inpaint_blend` — strength 0.35
  - → 완성 RGB PNG bytes 반환

**기본 파라미터 (run.py SSOT, 상수로 bake):**

| 항목 | 값 |
|---|---|
| blend mode | `inpaint` (상수 `_BLEND_MODE`로 토글, 대안 `img2img`) |
| inpaint strength | 0.35 |
| character img2img strength | 0.75 |
| steps | 8 (LCM) |
| char-scale / bg-scale | 1.0 / 1.0 (캐릭터 생성 시 bg_scale=0.3 오버라이드) |
| character seed / background seed | 42 / 랜덤 |

### 3.2 `pipeline.py` (워커)
- `adapter="feed"` 추가 — `LORA_CHARACTER_REPO` + `LORA_BG_REPO` 가 **둘 다** 있을 때 feed 모드 등록.
- `MultiAdapterImagePipeline.generate` 에 `scene_prompt: str | None = None` 인자 추가, 모드로 전달(character/bg 모드는 무시).
- **모드 lazy-load 전환**: 현재 `__init__` 에서 등록 모드를 전부 즉시 로드 → feed 추가 시 cold start 에 SDXL 3벌 로드 위험. 첫 요청 시 해당 모드만 로드하도록 변경.

### 3.3 `handler.py`
- `scene_prompt = job_input.get("scene_prompt")` 파싱, `generate(...)` 로 전달.
- adapter 검증 메시지에 `feed` 추가. docstring 갱신.

### 3.4 변경 불필요 (검증만)
- `bake.py`/Dockerfile: feed 가 쓰는 base SDXL·char·bg·lcm LoRA·rembg 는 character/bg 모드가 이미 bake → **신규 다운로드 없음**.
- `setup_endpoints.py`: `mongle-image-gen` 에 두 LoRA env 이미 설정됨 → 변경 없음.

---

## 4. 에이전트 변경 (`agents/feed_generation/`)

### 4.1 그래프 (`pipeline.py`)
신규 그래프: `gen_feed_prompt → feed_image → s3_upload → gen_caption_prompt → llm_caption → builder`
(구 `validate`, `bg`, `composite`, `validate_caption` 노드 제거)

### 4.2 노드
- **`gen_feed_prompt`**: **LLM** 으로 한글 `quest` 를 영문 `action`(포즈)/`scene`(배경)으로 분해(Hadimee VLM 방식), `visual` 과 결합 →
  - `feed_prompt.character` = visual + action
  - `feed_prompt.scene` = scene
  - RetryPolicy max=3 (LLM 호출). 기존 LLM 포트 재사용(신규 의존성 없음).
- **`feed_image`** (구 `img2img`): `generate_feed(reference_url, feed_prompt.character, feed_prompt.scene)` → `raw_image`(완성 PNG) → `s3_upload`. adapter=feed, RetryPolicy max=3.
- **`gen_caption_prompt`** (구 `assemble_caption_ctx`): 출력 `caption_ctx → caption_prompt`.
- **삭제**: `bg.py`(미커밋), `composite.py`(미커밋) — 워커로 이전. `validate.py`, `validate_caption.py` — 스키마로 이전.

### 4.3 state (`state.py`)
- `image_prompt` → `feed_prompt`(character/scene 보유), `raw_bg` 제거(합성이 워커 내부).

### 4.4 schemas (`schemas.py`) — 검증 스키마 이전 + 필드 개명
```python
class CharacterRef(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ...
    visual: list[str]                       # 구 appearance_keywords
    image_url: Annotated[str, Field(min_length=1)]   # 구 validate 노드

class QuestRef(BaseModel):
    ...
    quest: Annotated[str, Field(min_length=1, max_length=300)]  # 구 quest_text

class GeneratedFeed(BaseModel):
    ...
    caption: Annotated[str, Field(max_length=140)]
    @field_validator("caption")
    @classmethod
    def _must_contain_korean(cls, v: str) -> str:        # 구 validate_caption
        if not re.search(r"[가-힣]", v):
            raise ValueError("caption must contain Korean")
        return v
```

### 4.5 포트 / 어댑터
- `protocols.py` `ImageGeneratorPort`: feed 전용 `generate_img2img`/`generate_bg` → **`generate_feed(reference_url, character_prompt, scene_prompt) -> bytes`** 하나로 교체. 캐릭터 생성용 `generate()` 는 불변.
- `RunPodImageGenerator` (`adapters/character_creation/runpod_image.py`): `generate_feed` 추가, `_submit_and_poll` 에 `scene_prompt` payload 필드 추가, `adapter="feed"`.

---

## 5. 크로스-서비스 (mongle-server)

`appearance_keywords→visual`, `quest_text→quest` 스키마 개명은 입력 계약 변경(`extra="forbid"`). **mongle-server 가 `/v1/feed` 호출 시 보내는 payload 키도 동반 수정** 필요.

### 배포 순서 (역순 의존)
1. **워커** 재배포 (feed 모드 등록) — 기존 character/bg 호출 영향 없음(하위호환).
2. **mongle-ai** 배포 (generate_feed, 그래프/스키마 개명).
3. **mongle-server** payload 키 변경 배포 (mongle-ai 가 새 스키마 받을 준비된 뒤).

> mongle-ai 와 mongle-server 사이 개명은 한쪽만 바뀌면 깨지므로, mongle-ai 가 신 스키마를 받기 시작하는 시점과 mongle-server 가 신 키를 보내는 시점을 같은 릴리스로 묶거나, 2번에서 신·구 키를 한시적으로 둘 다 수용(alias)하는 호환 창을 둔다. — 구현 계획에서 확정.

---

## 6. 범위 밖 (follow-up)

- **local provider (`LoRAImageGenerator`) feed 패리티**: 현재 로컬 모드는 feed 메서드 자체가 없어 미지원(기존 공백). prod 는 RunPod 만 사용. 로컬 CUDA dev 박스가 실제 필요해질 때 5단계 로직을 공용 모듈로 추출하며 추가.
- 나쁜 캡션 시 LLM 재시도(현재·신규 모두 hard-fail 유지).

---

## 7. 테스트

- 에이전트: fake image generator 에 `generate_feed` 추가. `test_node_composite`/`test_node_bg` → `test_node_feed_image` 로 교체. `gen_feed_prompt`(LLM 분해) 테스트(fake LLM). `validate`/`validate_caption` 테스트 → 스키마 검증 테스트로 이전. 커버리지 80%+ 유지(글로벌 룰).
- 워커: GPU 추론은 CI 불가 → 머지 전 로컬 import 검증(`image_gen` 함정 메모리 관례). 가능하면 composite/mask 순수 함수는 CPU 단위 테스트.

---

## 8. 리스크

| 리스크 | 완화 |
|---|---|
| 엔드포인트가 character(생성)+feed 동시 서빙 → VRAM 압박 | 모드 lazy-load. feed 는 from_pipe 로 SDXL 1벌. 필요 시 bg 단독 모드 등록 제거. |
| mongle-server 개명 미스매치로 입력 파싱 실패 | 배포 순서 + (선택) 호환 창 alias. |
| RunPod 100s Pod 타임아웃 (5단계 추론 누적) | `_submit_and_poll` 폴링 방식(이미 비동기, timeout 600s) 사용 → Pod 동기 한계와 무관. |
| 캡션 검증 hard-fail 이 비싼 이미지/S3 작업 뒤에 발생 | 현행 동작 유지(범위 밖). |
