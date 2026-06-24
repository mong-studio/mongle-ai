# 일상(Daily-Life) SFT 데이터 파이프라인 구현 계획 (설계서 §4.6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 진짜 한국어 일상 후기/Q&A 를 크롤→GPT-4o 특징추출→결정론 타깃으로 가공해, planner 의 비-시험(일상) judge·generator·critic 노드 SFT 데이터를 시험 파이프라인과 동일한 모양으로 만든다.

**Architecture:** 시험 파이프라인(`crawl/ → structure/ → build/lib/ → mix → train → eval`)을 일상용으로 미러링한다. `crawl/`(robots·fetch·BeautifulSoup)은 도메인 무관이라 그대로 재사용하고, **GPT-4o 는 비정형 텍스트에서 features 만 추출**(구조 JSON 타깃은 코드 결정론)한다. 노드 system 프롬프트는 이미 plan_kind(일상 포함) 라우팅을 담아 **재사용**하며, 일상 빌더는 user/assistant 내용만 새로 만든다.

**Tech Stack:** Python 3.x, `uv`, pytest, BeautifulSoup/lxml, PyYAML, `openai`(추출 전용·게이팅), 기존 `sft_pipeline.*` 모듈.

## Global Constraints

설계서·코드베이스에서 추출한 전 작업 공통 제약. 모든 Task 의 요구사항에 암묵 포함된다.

- **불변성:** 입력 객체 변경 금지, 항상 새 객체 생성(`~/.claude/rules/coding-style.md`).
- **TDD:** 테스트 먼저(RED)→최소 구현(GREEN)→리팩토링. 새 로직마다 테스트 동반.
- **결정론 타깃 규율:** GPT-4o 는 **features 추출·노이즈 제거만** 한다. 구조 JSON(slots·plan·verdict) 최종 타깃은 **코드 결정론**. 순수 LLM 합성(맨바닥 생성) 금지. (§4.6, 시험 파이프라인 규율과 동일)
- **train==serve:** 모든 assistant 턴 == 런타임 노드가 방출하는 출력 JSON 과 정확히 동일. generator 타깃은 **현 런타임 `plan_generator` 계약(절대 날짜 `days[]`, 최대 7일, 하루 1~3 task, 전체 ≤12)** 을 미러한다. ⚠️ **`rel_day` 는 런타임에 미배선(`grep rel_day`=0건)이므로 SFT 에 넣지 않는다** — 설계서 §4.3 의 rel_day 타깃은 런타임 plan_generator 가 allocator 분업으로 재배선된 뒤(별도 Phase 2A, `2026-06-15-daily-life-planner-phase2a.md`)에만 적용. 이 계획은 현 계약을 따른다.
- **노드 system 프롬프트 재사용:** `PLANNER_JUDGE_SYSTEM`/`GOAL_TAG_SYSTEM`/`PLAN_GENERATOR_SYSTEM`/`PLAN_CRITIC_SYSTEM` 은 이미 plan_kind 4종(exam/routine/vague_goal/lifestyle) 라우팅을 담고 있다. 일상 빌더는 이 상수를 **import 재사용**하고 새 system 프롬프트를 만들지 않는다. 드리프트는 기존 `test_*_template.py::test_mirror_matches_runtime` 가 잡는다.
- **새 provenance = `"daily-crawl"`:** `validate_dataset.PLAN_PROVENANCES`, `validate_dataset._horizon_days`(7일), `mix_dataset._PUBLIC_ALLOWED`(라이선스 확인 후) 에 등록.
- **§4.4/D10 supersede:** `content_library.yaml`(수제 큐레이션)은 §4.6 이 폐기했다. **만들지 않는다.** 일상 plan 내용은 크롤에서 추출한 `real_breakdown` 에서 온다.
- **크롤 위생:** `crawl/robots.py` 재사용(robots 준수), 요청 간 ≥1초 sleep, 공식/허용 도메인만, ToS 보수적 준수.
- **언어 게이트:** 한국어만. 가나·키릴·태국 문자 0, 한자 비율 ≤2%(기존 `validate_dataset` 게이트가 강제).
- **품질 안티패턴(§4.6 2차 라이브 피드백):** 필러 잡무("운동복 확인", "기구 점검", "간식 정리") 금지 — generator 타깃은 추출된 `real_breakdown` 그대로, critic 에 triviality(잡무 비율) 체크 추가.
- **파일 크기:** 200~400줄(최대 800), 함수 <50줄, 기능/도메인별 구성.
- **결정성 타임스탬프:** 빌드는 `--today` 고정 옵션으로 재현 가능해야 한다(기존 빌더 관례).

## File Structure

**신규 (Stage ① — 크롤·추출·구조화):**
- `sft_pipeline/config/daily_taxonomy.yaml` — plan_kind 별칭 + 도메인 택소노미(운동·학습·휴식·관계·정리)
- `sft_pipeline/structure/daily_taxonomy.py` — plan_kind·domain 정규화(`exam_types.py` 대응)
- `sft_pipeline/structure/daily_normalize.py` — cadence·time_of_day·horizon 파싱(`normalize.py` 대응)
- `sft_pipeline/structure/daily_fields.py` — `StructuredDailyCase` + `structure_daily_row`(`fields.py` 대응)
- `sft_pipeline/structure/run_daily_structure.py` — raw_daily.csv → structured_daily.csv(`run_structure.py` 대응)
- `sft_pipeline/crawl/daily_extractor.py` — GPT-4o: extracted_text → raw_daily 필드(features 추출 전용)

**신규 (Stage ② — 노드 빌더·검증):**
- `sft_pipeline/build/lib/daily_nodes_template.py` — 일상 judge/goal_tag/generator/critic 의 user·assistant 내용 빌더(system 은 재사용)
- `sft_pipeline/build/lib/build_daily_nodes_sft.py` — structured_daily.csv → 일상 노드 SFT jsonl
- `sft_pipeline/build/lib/build_daily_followup_sft.py` — 멀티턴 follow-up 트레이스(≤2턴, D9)

**변경:**
- `sft_pipeline/config/extractors.yaml` — 일상 소스 도메인 셀렉터 추가
- `sft_pipeline/build/lib/validate_dataset.py` — `daily-crawl` provenance 등록 + 일상 meta 필수키
- `sft_pipeline/build/lib/coherence_eval.py` — triviality(잡무) 자동 근사 지표 추가
- `sft_pipeline/build/lib/mix_dataset.py` — `daily-crawl` 공개 화이트리스트 등록(라이선스 확인 후)

**테스트:** 각 신규 모듈마다 `sft_pipeline/tests/test_<module>.py`.

**비범위(이 계획 밖):** 런타임 rel_day/allocator 재배선(Phase 2A), GPU 학습 실행, 라이브 크롤 대량 실행(키·네트워크 게이팅), CJK 깨짐 repair 적용(`todo-title-corruption-repair` 별도 작업).

---

## Stage ① — 크롤 + 추출 (품질 게이트 먼저)

### Task 1: 일상 택소노미 (`daily_taxonomy.py` + yaml)

plan_kind 별칭과 도메인을 표준코드로 정규화한다. `exam_types.py` 와 동형(매칭 실패 시 None, 추정 금지).

**Files:**
- Create: `sft_pipeline/config/daily_taxonomy.yaml`
- Create: `sft_pipeline/structure/daily_taxonomy.py`
- Test: `sft_pipeline/tests/test_daily_taxonomy.py`

**Interfaces:**
- Produces:
  - `canonicalize_plan_kind(raw: str | None) -> str | None` — {exam,routine,vague_goal,lifestyle} 중 하나 또는 None
  - `canonicalize_domain(raw: str | None) -> str | None` — {운동,학습,휴식,관계,정리} 중 하나 또는 None
  - `VALID_PLAN_KINDS: set[str]`, `VALID_DOMAINS: set[str]`

- [ ] **Step 1: yaml 작성**

Create `sft_pipeline/config/daily_taxonomy.yaml`:
```yaml
# plan_kind 표준코드: [별칭]  (소문자·공백제거 후 완전일치, 추정 금지)
plan_kinds:
  routine:
    - 루틴
    - 습관
    - 반복
  vague_goal:
    - 막연한목표
    - 꾸준히
    - 잘하고싶다
  lifestyle:
    - 생활설계
    - 라이프스타일
    - 균형
  exam:
    - 시험
    - 자격증
# domain 표준코드: [별칭]
domains:
  운동:
    - 헬스
    - 런닝
    - 러닝
    - 요가
    - 홈트
  학습:
    - 공부
    - 영어
    - 독서
    - 강의
  휴식:
    - 명상
    - 수면
    - 휴식
  관계:
    - 가족
    - 친구
    - 모임
  정리:
    - 청소
    - 정돈
    - 가계부
```

- [ ] **Step 2: 실패 테스트 작성**

Create `sft_pipeline/tests/test_daily_taxonomy.py`:
```python
from sft_pipeline.structure.daily_taxonomy import (
    canonicalize_domain,
    canonicalize_plan_kind,
)


def test_plan_kind_alias_maps_to_canonical():
    assert canonicalize_plan_kind("루틴") == "routine"
    assert canonicalize_plan_kind("라이프스타일") == "lifestyle"


def test_plan_kind_normalizes_spaces_and_case():
    assert canonicalize_plan_kind(" 막연한 목표 ") == "vague_goal"


def test_unknown_plan_kind_returns_none():
    assert canonicalize_plan_kind("기상천외") is None
    assert canonicalize_plan_kind("") is None
    assert canonicalize_plan_kind(None) is None


def test_domain_alias_maps_to_canonical():
    assert canonicalize_domain("헬스") == "운동"
    assert canonicalize_domain("영어") == "학습"


def test_unknown_domain_returns_none():
    assert canonicalize_domain("우주여행") is None
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_taxonomy.py -v`
Expected: FAIL — `ModuleNotFoundError: ... daily_taxonomy`

- [ ] **Step 4: 구현**

Create `sft_pipeline/structure/daily_taxonomy.py` (`exam_types.py` 패턴 재사용 — 두 매핑 섹션):
```python
"""plan_kind·domain 별칭 → 표준코드. 매칭 실패 시 None (추정 금지)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "daily_taxonomy.yaml"


def _norm(text: str) -> str:
    return text.lower().replace(" ", "").replace("_", "")


@lru_cache(maxsize=1)
def _config() -> dict:
    with open(_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _index(section: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for canonical, aliases in _config()[section].items():
        pairs.append((_norm(canonical), canonical))
        for alias in aliases:
            pairs.append((_norm(alias), canonical))
    pairs = list(dict.fromkeys(pairs))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


@lru_cache(maxsize=1)
def _plan_kind_index() -> list[tuple[str, str]]:
    return _index("plan_kinds")


@lru_cache(maxsize=1)
def _domain_index() -> list[tuple[str, str]]:
    return _index("domains")


def _lookup(index: list[tuple[str, str]], raw: str | None) -> str | None:
    needle = _norm(raw or "")
    if not needle:
        return None
    for alias_norm, canonical in index:
        if alias_norm == needle:
            return canonical
    return None


def canonicalize_plan_kind(raw: str | None) -> str | None:
    return _lookup(_plan_kind_index(), raw)


def canonicalize_domain(raw: str | None) -> str | None:
    return _lookup(_domain_index(), raw)


VALID_PLAN_KINDS = {"exam", "routine", "vague_goal", "lifestyle"}
VALID_DOMAINS = {"운동", "학습", "휴식", "관계", "정리"}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_taxonomy.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: 커밋**

```bash
git add sft_pipeline/config/daily_taxonomy.yaml sft_pipeline/structure/daily_taxonomy.py sft_pipeline/tests/test_daily_taxonomy.py
git commit -m "feat: 일상 plan_kind·domain 택소노미 추가 (§4.6 Stage ①)"
```

---

### Task 2: 일상 정규화 (`daily_normalize.py`)

cadence("주3회"/"월수금"/"매일"), time_of_day, horizon("한 달"→28일) 을 파싱한다. cadence 파싱은 런타임 `allocator.cadence_is_specific` 의 정책과 정합해야 한다(structure 단계는 모호성 플래그만 판단).

**Files:**
- Create: `sft_pipeline/structure/daily_normalize.py`
- Test: `sft_pipeline/tests/test_daily_normalize.py`

**Interfaces:**
- Consumes: `sft_pipeline.structure.normalize.parse_time_left`(horizon 일수 재사용)
- Produces:
  - `parse_cadence(raw: str | None) -> Cadence` — `Cadence(specific: bool, raw: str)` frozen dataclass
  - `parse_horizon_days(raw: str | None) -> int | None` — "한 달"→30, "4주"→28, 모호/미기재→None
  - `parse_time_of_day(raw: str | None) -> str` — {아침,오전,점심,오후,저녁,밤,""} 중 하나(미상→"")

- [ ] **Step 1: 실패 테스트 작성**

Create `sft_pipeline/tests/test_daily_normalize.py`:
```python
from sft_pipeline.structure.daily_normalize import (
    parse_cadence,
    parse_horizon_days,
    parse_time_of_day,
)


def test_cadence_weekly_count_is_specific():
    assert parse_cadence("주 3회").specific is True


def test_cadence_weekdays_is_specific():
    assert parse_cadence("월수금").specific is True


def test_cadence_daily_is_specific():
    assert parse_cadence("매일").specific is True


def test_cadence_vague_is_not_specific():
    assert parse_cadence("매주").specific is False
    assert parse_cadence("").specific is False


def test_horizon_keyword_and_units():
    assert parse_horizon_days("한 달") == 30
    assert parse_horizon_days("4주") == 28
    assert parse_horizon_days("언젠가") is None
    assert parse_horizon_days(None) is None


def test_time_of_day_maps_known_words():
    assert parse_time_of_day("아침에") == "아침"
    assert parse_time_of_day("저녁 운동") == "저녁"
    assert parse_time_of_day("아무때나") == ""
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

Create `sft_pipeline/structure/daily_normalize.py`:
```python
"""일상 cadence·time_of_day·horizon 정규화. 추정 금지: 모호하면 None/빈값."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sft_pipeline.structure.normalize import parse_time_left

_WEEKDAY_CHARS = set("월화수목금토일")
_DAILY_WORDS = ("매일", "날마다", "데일리")
_TIME_WORDS = ("아침", "오전", "점심", "오후", "저녁", "밤")


@dataclass(frozen=True)
class Cadence:
    specific: bool
    raw: str


def parse_cadence(raw: str | None) -> Cadence:
    text = (raw or "").replace(" ", "")
    if not text:
        return Cadence(False, raw or "")
    if any(w in text for w in _DAILY_WORDS):
        return Cadence(True, raw or "")
    if any(ch in _WEEKDAY_CHARS for ch in text):
        return Cadence(True, raw or "")
    return Cadence(bool(re.search(r"\d", text)), raw or "")


def parse_horizon_days(raw: str | None) -> int | None:
    return parse_time_left(raw).days


def parse_time_of_day(raw: str | None) -> str:
    text = raw or ""
    for word in _TIME_WORDS:
        if word in text:
            return word
    return ""
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_normalize.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add sft_pipeline/structure/daily_normalize.py sft_pipeline/tests/test_daily_normalize.py
git commit -m "feat: 일상 cadence·horizon·time_of_day 정규화 (§4.6 Stage ①)"
```

---

### Task 3: 구조화 케이스 (`daily_fields.py`)

raw_daily 행 → `StructuredDailyCase`. 누락값 정책: 미기재→빈값/None, 추정 금지, 모호→review_flags. `fields.py` 와 동형.

**Files:**
- Create: `sft_pipeline/structure/daily_fields.py`
- Test: `sft_pipeline/tests/test_daily_fields.py`

**Interfaces:**
- Consumes: `daily_taxonomy.canonicalize_plan_kind/canonicalize_domain`, `daily_normalize.parse_cadence/parse_horizon_days/parse_time_of_day`
- Produces:
  - `StructuredDailyCase` frozen dataclass — fields: `source_url, source_type, plan_kind, goal_text, activity, domains(list[str]), cadence, cadence_specific(bool), time_of_day, horizon_days(int|None), trigger, real_breakdown, review_flags(list[str])`
  - `structure_daily_row(row: dict) -> StructuredDailyCase`
  - `RAW_DAILY_COLUMNS: list[str]` — 입력 csv 컬럼

`real_breakdown` 입력은 `"활동|빈도|시간대; 활동|빈도|시간대"` 형식 문자열(추출기가 채움); structure 는 검증만 하고 통과시킨다(파싱은 generator 빌더 책임). `domains` 입력은 `;` 구분 문자열.

- [ ] **Step 1: 실패 테스트 작성**

Create `sft_pipeline/tests/test_daily_fields.py`:
```python
from sft_pipeline.structure.daily_fields import structure_daily_row


def _row(**over):
    base = {
        "source_url": "https://blog.example.com/1",
        "source_type": "blog",
        "plan_kind": "루틴",
        "goal_text": "꾸준히 운동",
        "activity": "헬스",
        "domains": "운동",
        "cadence": "주 3회",
        "time_of_day": "저녁",
        "horizon": "한 달",
        "trigger": "건강검진 경고",
        "real_breakdown": "주3회 헬스|주3|저녁",
    }
    base.update(over)
    return base


def test_maps_plan_kind_and_domains():
    case = structure_daily_row(_row())
    assert case.plan_kind == "routine"
    assert case.domains == ["운동"]
    assert case.cadence_specific is True
    assert case.horizon_days == 30
    assert case.review_flags == []


def test_unmapped_plan_kind_flags_and_blanks():
    case = structure_daily_row(_row(plan_kind="기상천외"))
    assert case.plan_kind == ""
    assert "plan_kind_unmapped" in case.review_flags


def test_vague_cadence_flagged():
    case = structure_daily_row(_row(cadence="매주"))
    assert case.cadence_specific is False
    assert "cadence_vague" in case.review_flags


def test_missing_real_breakdown_flagged():
    case = structure_daily_row(_row(real_breakdown=""))
    assert "real_breakdown_missing" in case.review_flags


def test_unknown_domain_dropped_and_flagged():
    case = structure_daily_row(_row(domains="운동;우주여행"))
    assert case.domains == ["운동"]
    assert "domain_unmapped" in case.review_flags
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_fields.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

Create `sft_pipeline/structure/daily_fields.py`:
```python
"""일상 구조화 케이스 스키마. 미기재→빈값/None, 추정 금지, 모호→review_flags."""
from __future__ import annotations

from dataclasses import dataclass, field

from sft_pipeline.structure.daily_normalize import (
    parse_cadence,
    parse_horizon_days,
    parse_time_of_day,
)
from sft_pipeline.structure.daily_taxonomy import (
    canonicalize_domain,
    canonicalize_plan_kind,
)

RAW_DAILY_COLUMNS = [
    "source_url",
    "source_type",
    "plan_kind",
    "goal_text",
    "activity",
    "domains",
    "cadence",
    "time_of_day",
    "horizon",
    "trigger",
    "real_breakdown",
]


@dataclass(frozen=True)
class StructuredDailyCase:
    source_url: str
    source_type: str
    plan_kind: str
    goal_text: str
    activity: str
    domains: list[str]
    cadence: str
    cadence_specific: bool
    time_of_day: str
    horizon_days: int | None
    trigger: str
    real_breakdown: str
    review_flags: list[str] = field(default_factory=list)


def _clean(row: dict, key: str) -> str:
    return (row.get(key, "") or "").strip()


def _domains(raw: str, flags: list[str]) -> list[str]:
    out: list[str] = []
    for token in (t.strip() for t in raw.split(";") if t.strip()):
        canonical = canonicalize_domain(token)
        if canonical is None:
            flags.append("domain_unmapped")
        elif canonical not in out:
            out.append(canonical)
    return out


def structure_daily_row(row: dict) -> StructuredDailyCase:
    flags: list[str] = []

    plan_kind = canonicalize_plan_kind(_clean(row, "plan_kind"))
    if plan_kind is None:
        flags.append("plan_kind_unmapped")
        plan_kind = ""

    cadence_raw = _clean(row, "cadence")
    cadence = parse_cadence(cadence_raw)
    # exam/lifestyle 은 cadence 가 핵심 슬롯이 아니므로 vague 플래그를 강제하지 않는다.
    if plan_kind in ("routine", "vague_goal") and cadence_raw and not cadence.specific:
        flags.append("cadence_vague")

    real_breakdown = _clean(row, "real_breakdown")
    if not real_breakdown:
        flags.append("real_breakdown_missing")

    return StructuredDailyCase(
        source_url=_clean(row, "source_url"),
        source_type=_clean(row, "source_type"),
        plan_kind=plan_kind,
        goal_text=_clean(row, "goal_text"),
        activity=_clean(row, "activity"),
        domains=_domains(_clean(row, "domains"), flags),
        cadence=cadence_raw,
        cadence_specific=cadence.specific,
        time_of_day=parse_time_of_day(_clean(row, "time_of_day")),
        horizon_days=parse_horizon_days(_clean(row, "horizon")),
        trigger=_clean(row, "trigger"),
        real_breakdown=real_breakdown,
        review_flags=flags,
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_fields.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add sft_pipeline/structure/daily_fields.py sft_pipeline/tests/test_daily_fields.py
git commit -m "feat: 일상 구조화 케이스 스키마 (§4.6 Stage ①)"
```

---

### Task 4: 구조화 러너 (`run_daily_structure.py`)

raw_daily.csv → structured_daily.csv. `run_structure.py` 와 동형(주석 행 스킵, DictWriter).

**Files:**
- Create: `sft_pipeline/structure/run_daily_structure.py`
- Test: `sft_pipeline/tests/test_run_daily_structure.py`

**Interfaces:**
- Consumes: `daily_fields.structure_daily_row`, `StructuredDailyCase`
- Produces:
  - `STRUCTURED_DAILY_COLUMNS: list[str]`
  - `write_structured_daily(rows: list[dict], out_path: Path) -> int`
  - `read_raw_daily(path: Path) -> list[dict]`

- [ ] **Step 1: 실패 테스트 작성**

Create `sft_pipeline/tests/test_run_daily_structure.py`:
```python
import csv

from sft_pipeline.structure.run_daily_structure import (
    STRUCTURED_DAILY_COLUMNS,
    write_structured_daily,
)


def test_writes_structured_csv_with_lists_joined(tmp_path):
    rows = [
        {
            "source_url": "https://blog.example.com/1",
            "source_type": "blog",
            "plan_kind": "루틴",
            "goal_text": "꾸준히 운동",
            "activity": "헬스",
            "domains": "운동;학습",
            "cadence": "주 3회",
            "time_of_day": "저녁",
            "horizon": "한 달",
            "trigger": "건강검진",
            "real_breakdown": "주3회 헬스|주3|저녁",
        }
    ]
    out = tmp_path / "structured_daily.csv"
    n = write_structured_daily(rows, out)
    assert n == 1
    with open(out, encoding="utf-8") as f:
        record = next(csv.DictReader(f))
    assert record["plan_kind"] == "routine"
    assert record["domains"] == "운동;학습"
    assert record["horizon_days"] == "30"
    assert set(STRUCTURED_DAILY_COLUMNS).issubset(record.keys())
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest sft_pipeline/tests/test_run_daily_structure.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

Create `sft_pipeline/structure/run_daily_structure.py`:
```python
"""raw_daily.csv → structured_daily.csv (검증·정규화). #로 시작하는 행은 주석."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sft_pipeline.structure.daily_fields import StructuredDailyCase, structure_daily_row

STRUCTURED_DAILY_COLUMNS = [
    "source_url",
    "source_type",
    "plan_kind",
    "goal_text",
    "activity",
    "domains",
    "cadence",
    "cadence_specific",
    "time_of_day",
    "horizon_days",
    "trigger",
    "real_breakdown",
    "review_flags",
]


def read_raw_daily(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            row
            for row in reader
            if row.get("source_url") and not row["source_url"].lstrip().startswith("#")
        ]


def _to_record(case: StructuredDailyCase) -> dict:
    return {
        "source_url": case.source_url,
        "source_type": case.source_type,
        "plan_kind": case.plan_kind,
        "goal_text": case.goal_text,
        "activity": case.activity,
        "domains": ";".join(case.domains),
        "cadence": case.cadence,
        "cadence_specific": str(case.cadence_specific),
        "time_of_day": case.time_of_day,
        "horizon_days": "" if case.horizon_days is None else case.horizon_days,
        "trigger": case.trigger,
        "real_breakdown": case.real_breakdown,
        "review_flags": ";".join(case.review_flags),
    }


def write_structured_daily(rows: list[dict], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records = [_to_record(structure_daily_row(r)) for r in rows]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STRUCTURED_DAILY_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="raw_daily.csv → structured_daily.csv")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()
    rows = read_raw_daily(args.in_path)
    n = write_structured_daily(rows, args.out_path)
    print(f"structured {n} daily cases -> {args.out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_run_daily_structure.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: 커밋**

```bash
git add sft_pipeline/structure/run_daily_structure.py sft_pipeline/tests/test_run_daily_structure.py
git commit -m "feat: 일상 구조화 러너 (§4.6 Stage ①)"
```

---

### Task 5: GPT-4o 특징 추출기 (`daily_extractor.py`)

크롤 `extracted_text` → raw_daily 필드 dict. **GPT-4o 는 features 만 추출**(구조 타깃 아님). Fake 클라이언트로 테스트하고, 라이브 호출은 `OPENAI_API_KEY` 있을 때만. `make_client`(rephrase.py) 재사용. 협찬/광고는 추출 신뢰도 점수로 필터.

**Files:**
- Create: `sft_pipeline/crawl/daily_extractor.py`
- Modify: `sft_pipeline/config/extractors.yaml` (일상 도메인 셀렉터 — 이미 naver/tistory 있음, 확인만)
- Test: `sft_pipeline/tests/test_daily_extractor.py`

**Interfaces:**
- Consumes: `sft_pipeline.build.lib.rephrase.make_client`
- Produces:
  - `EXTRACT_SYSTEM: str` — 추출 지시(features only, JSON)
  - `extract_daily_features(text: str, *, source_url: str, source_type: str, client=None, model: str = "gpt-4o", temperature: float = 0.0) -> dict | None` — `client=None`(키 없음)이면 `None`(라이브 게이팅). 반환 dict 는 `RAW_DAILY_COLUMNS` 키 + `confidence(float)`.
  - `build_client_from_env()` — `rephrase.make_client` 위임(키 없으면 None)

추출기는 LLM 응답 JSON 을 그대로 신뢰하지 않고 `confidence < 0.5` 또는 `ad=true` 면 `None` 반환(드롭). 테스트는 응답을 주입하는 Fake 로 라이브 호출 0.

- [ ] **Step 1: 실패 테스트 작성**

Create `sft_pipeline/tests/test_daily_extractor.py`:
```python
import json

from sft_pipeline.crawl.daily_extractor import extract_daily_features


class _FakeResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})})]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return _FakeResp(self._content)


class _FakeClient:
    def __init__(self, content):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})


def _payload(**over):
    base = {
        "plan_kind": "routine",
        "goal_text": "꾸준히 운동",
        "activity": "헬스",
        "domains": "운동",
        "cadence": "주 3회",
        "time_of_day": "저녁",
        "horizon": "한 달",
        "trigger": "건강검진 경고",
        "real_breakdown": "주3회 헬스|주3|저녁",
        "confidence": 0.9,
        "ad": False,
    }
    base.update(over)
    return base


def test_no_client_returns_none():
    assert extract_daily_features("본문", source_url="u", source_type="blog", client=None) is None


def test_extracts_fields_from_client():
    client = _FakeClient(json.dumps(_payload()))
    out = extract_daily_features("본문", source_url="u", source_type="blog", client=client)
    assert out["plan_kind"] == "routine"
    assert out["source_url"] == "u"
    assert out["real_breakdown"] == "주3회 헬스|주3|저녁"


def test_low_confidence_dropped():
    client = _FakeClient(json.dumps(_payload(confidence=0.2)))
    assert extract_daily_features("본문", source_url="u", source_type="blog", client=client) is None


def test_ad_flagged_dropped():
    client = _FakeClient(json.dumps(_payload(ad=True)))
    assert extract_daily_features("본문", source_url="u", source_type="blog", client=client) is None


def test_invalid_json_returns_none():
    client = _FakeClient("not json")
    assert extract_daily_features("본문", source_url="u", source_type="blog", client=client) is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

Create `sft_pipeline/crawl/daily_extractor.py`:
```python
"""크롤 본문 → 일상 raw_daily 필드(GPT-4o 추출 전용, 구조 타깃 아님).

GPT-4o 는 비정형 후기에서 features 를 뽑고 광고/협찬을 거른다(§4.6).
구조 JSON 최종 타깃은 하류 빌더의 코드 결정론. 라이브 호출은 키 있을 때만.
"""
from __future__ import annotations

import json
import logging

from sft_pipeline.build.lib.rephrase import make_client

log = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.5

EXTRACT_SYSTEM = """
너는 한국어 생활/후기 글에서 '실제 실행한 계획'의 특징만 뽑아내는 추출기다.
글에 실제로 적힌 내용만 추출하고, 없는 값은 빈 문자열로 둔다(추측·창작 금지).
광고/협찬/체험단 글은 ad=true 로 표시한다.

[출력 규칙]
- 반드시 JSON 객체 하나만 출력한다. 마크다운·설명 금지.
- 스키마:
{
  "plan_kind": "routine|vague_goal|lifestyle|exam 또는 빈문자열",
  "goal_text": "글쓴이의 목표 요약",
  "activity": "핵심 활동(단일)",
  "domains": "운동;학습 처럼 세미콜론 구분",
  "cadence": "주3회 / 월수금 / 매일 등 빈도(원문 표현)",
  "time_of_day": "아침|오전|점심|오후|저녁|밤 또는 빈문자열",
  "horizon": "한 달 / 4주 등 기간(원문 표현)",
  "trigger": "계획을 시작한 계기",
  "real_breakdown": "실제 활동을 '활동|빈도|시간대'로, 여러 개는 세미콜론 구분. 준비/점검/정리 같은 잡무는 넣지 마라.",
  "confidence": 0.0~1.0,
  "ad": true | false
}
"""


def build_client_from_env():
    return make_client()


def _user(text: str) -> str:
    return f"다음 글에서 특징을 추출해라:\n{text}"


def extract_daily_features(
    text: str,
    *,
    source_url: str,
    source_type: str,
    client=None,
    model: str = "gpt-4o",
    temperature: float = 0.0,
) -> dict | None:
    if client is None:
        return None
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": _user(text)},
            ],
            temperature=temperature,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as exc:  # noqa: BLE001 - 추출 실패는 그 케이스를 드롭(품질 게이트)
        log.warning("일상 추출 실패(드롭): %s", exc)
        return None

    if data.get("ad") is True:
        return None
    try:
        if float(data.get("confidence", 0)) < _MIN_CONFIDENCE:
            return None
    except (TypeError, ValueError):
        return None

    return {
        "source_url": source_url,
        "source_type": source_type,
        "plan_kind": data.get("plan_kind", ""),
        "goal_text": data.get("goal_text", ""),
        "activity": data.get("activity", ""),
        "domains": data.get("domains", ""),
        "cadence": data.get("cadence", ""),
        "time_of_day": data.get("time_of_day", ""),
        "horizon": data.get("horizon", ""),
        "trigger": data.get("trigger", ""),
        "real_breakdown": data.get("real_breakdown", ""),
        "confidence": data.get("confidence", 0),
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_extractor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: extractors.yaml 확인 (변경 불요 가능)**

`sft_pipeline/config/extractors.yaml` 에 `blog.naver.com`·`*.tistory.com` 셀렉터가 이미 있다. 새 일상 소스 도메인을 추가할 때만 엔트리를 더한다. 이번엔 확인만(no-op 가능).

- [ ] **Step 6: 커밋**

```bash
git add sft_pipeline/crawl/daily_extractor.py sft_pipeline/tests/test_daily_extractor.py
git commit -m "feat: 일상 GPT-4o 특징 추출기 (features-only, 게이팅) (§4.6 Stage ①)"
```

---

## Stage ② — 노드 빌더 + 검증

### Task 6: 일상 노드 내용 빌더 (`daily_nodes_template.py`)

structured_daily 케이스 → judge·goal_tag·generator·critic 의 user·assistant 내용. **system 프롬프트는 기존 템플릿 상수 재사용**(import). judge 는 **안티-환각**(추출된 슬롯만, 저정보면 is_sufficient=false), generator 는 **real_breakdown 기반 절대-날짜 days[]**(현 런타임 계약), critic 은 positive + off-goal/triviality negative.

**Files:**
- Create: `sft_pipeline/build/lib/daily_nodes_template.py`
- Test: `sft_pipeline/tests/test_daily_nodes_template.py`

**Interfaces:**
- Consumes (재사용 import):
  - `planner_nodes_template`: `PLANNER_JUDGE_SYSTEM`, `GOAL_TAG_SYSTEM`, `planner_judge_user`, `goal_tag_user`
  - `plan_generator_template`: `PLAN_GENERATOR_SYSTEM`, `plan_generator_user`, `_as_jsonable`, `_curve_difficulty`
  - `plan_critic_template`: `PLAN_CRITIC_SYSTEM`, `plan_critic_user`, `_overloaded_days`
  - `agents.todo_creation.planner.slot_schemas`: `missing_required`
- Produces:
  - `build_daily_parsed_goal(case: dict, today: date) -> dict`
  - `daily_filled_slot_keys(case: dict) -> set[str]`
  - `is_daily_sufficient(case: dict) -> tuple[bool, list[str]]`
  - `parse_real_breakdown(raw: str) -> list[dict]`
  - `build_daily_days(case: dict, today: date) -> list[dict]`
  - `build_judge_record / build_goal_tag_record / build_generator_record / build_critic_records(case, today)`
  - `build_records(case: dict, today: date) -> list[dict]` — sufficient 면 [judge, goal_tag, generator, *critic]; insufficient 면 [judge]

판정은 런타임 `slot_schemas.missing_required` 를 **직접 재사용**(train==serve).

- [ ] **Step 1: 실패 테스트 작성**

Create `sft_pipeline/tests/test_daily_nodes_template.py`:
```python
import json
from datetime import date

from sft_pipeline.build.lib.daily_nodes_template import (
    build_daily_days,
    build_records,
    is_daily_sufficient,
    parse_real_breakdown,
)

TODAY = date(2026, 6, 24)


def _routine_case(**over):
    base = {
        "source_url": "u",
        "source_type": "blog",
        "plan_kind": "routine",
        "goal_text": "꾸준히 운동",
        "activity": "헬스",
        "domains": "운동",
        "cadence": "주 3회",
        "time_of_day": "저녁",
        "horizon_days": "30",
        "trigger": "건강검진",
        "real_breakdown": "주3회 헬스|주3|저녁;런닝 30분|주2|아침",
    }
    base.update(over)
    return base


def test_routine_with_required_slots_is_sufficient():
    ok, missing = is_daily_sufficient(_routine_case())
    assert ok is True
    assert missing == []


def test_routine_missing_cadence_is_insufficient():
    ok, missing = is_daily_sufficient(_routine_case(cadence=""))
    assert ok is False
    assert "cadence" in missing


def test_parse_real_breakdown_splits_fields():
    items = parse_real_breakdown("주3회 헬스|주3|저녁;런닝 30분|주2|아침")
    assert items[0]["title"] == "주3회 헬스"
    assert items[1]["time_of_day"] == "아침"


def test_build_daily_days_respects_contract():
    days = build_daily_days(_routine_case(), TODAY)
    assert 1 <= len(days) <= 7
    total = sum(len(d["tasks"]) for d in days)
    assert total <= 12
    for d in days:
        assert 1 <= len(d["tasks"]) <= 3
        for t in d["tasks"]:
            assert t["due_date"] == d["date"]
    titles = [t["title"] for d in days for t in d["tasks"]]
    assert not any("점검" in x or "확인" in x or "정리" in x for x in titles)


def test_build_records_sufficient_emits_all_nodes():
    records = build_records(_routine_case(), TODAY)
    nodes = {r["meta"]["node"] for r in records}
    assert {"judge", "goal_tag", "generator", "critic"} <= nodes
    assert all(r["meta"]["provenance"] in ("daily-crawl", "daily-critic") for r in records)


def test_build_records_insufficient_emits_judge_only():
    records = build_records(_routine_case(cadence=""), TODAY)
    judge = [r for r in records if r["meta"]["node"] == "judge"][0]
    assistant = json.loads(judge["messages"][-1]["content"])
    assert assistant["is_sufficient"] is False
    assert "generator" not in {r["meta"]["node"] for r in records}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_nodes_template.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

Create `sft_pipeline/build/lib/daily_nodes_template.py`:
```python
"""structured_daily 케이스 → 일상 planner 노드 SFT 레코드(judge/goal_tag/generator/critic).

system 프롬프트는 런타임 미러 상수를 재사용한다(plan_kind 라우팅을 이미 담음).
판정은 런타임 slot_schemas.missing_required 를 직접 재사용 = train==serve.
generator 타깃은 현 런타임 계약(절대 날짜 days[], ≤7일·하루≤3·≤12)을 미러하되
내용은 추출된 real_breakdown 그대로(필러 잡무 합성 금지, §4.6).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from agents.todo_creation.planner.slot_schemas import missing_required
from sft_pipeline.build.lib.plan_critic_template import (
    PLAN_CRITIC_SYSTEM,
    _overloaded_days,
    plan_critic_user,
)
from sft_pipeline.build.lib.plan_generator_template import (
    PLAN_GENERATOR_SYSTEM,
    _as_jsonable,
    _curve_difficulty,
    plan_generator_user,
)
from sft_pipeline.build.lib.planner_nodes_template import (
    GOAL_TAG_SYSTEM,
    PLANNER_JUDGE_SYSTEM,
    goal_tag_user,
    planner_judge_user,
)

_HORIZON_DAYS = 7
_MAX_TASKS = 12

# structured_daily 컬럼 → slot_schemas 슬롯 key 매핑(plan_kind 별).
_SLOT_SOURCES: dict[str, dict[str, str]] = {
    "routine": {"activity": "activity", "cadence": "cadence"},
    "vague_goal": {"goal": "goal_text", "first_action": "activity", "weekly_cadence": "cadence"},
    "lifestyle": {"domains": "domains", "cadence_per_domain": "cadence", "horizon": "horizon_days"},
    "exam": {},
}


def daily_filled_slot_keys(case: dict) -> set[str]:
    sources = _SLOT_SOURCES.get(case.get("plan_kind", ""), {})
    return {slot for slot, col in sources.items() if str(case.get(col, "")).strip()}


def is_daily_sufficient(case: dict) -> tuple[bool, list[str]]:
    plan_kind = case.get("plan_kind", "")
    missing = missing_required(plan_kind, daily_filled_slot_keys(case))
    return (not missing), missing


def _slots_dict(case: dict) -> dict[str, str]:
    sources = _SLOT_SOURCES.get(case.get("plan_kind", ""), {})
    return {
        slot: str(case.get(col, "")).strip()
        for slot, col in sources.items()
        if str(case.get(col, "")).strip()
    }


def _goal_tag(case: dict) -> str:
    text = (case.get("goal_text") or case.get("activity") or "목표").strip()
    return text.replace(" ", "")[:20] or "목표"


def build_daily_parsed_goal(case: dict, today: date) -> dict[str, Any]:
    return {
        "intent": "plan",
        "plan_kind": case.get("plan_kind", ""),
        "slots": _slots_dict(case),
        "goal_text": case.get("goal_text") or case.get("activity") or "목표",
        "goal_tag": _goal_tag(case),
        "deadline": None,
        "daily_capacity_minutes": None,
        "personalization_patch": {"preferences": [], "constraints": []},
    }


def parse_real_breakdown(raw: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for chunk in (c.strip() for c in (raw or "").split(";") if c.strip()):
        parts = [p.strip() for p in chunk.split("|")]
        title = parts[0][:20] if parts else ""
        if not title:
            continue
        items.append(
            {
                "title": title,
                "cadence": parts[1] if len(parts) > 1 else "",
                "time_of_day": parts[2] if len(parts) > 2 else "",
            }
        )
    return items


def build_daily_days(case: dict, today: date) -> list[dict[str, Any]]:
    """real_breakdown 활동을 today 부터 하루 1개씩 펼친다(현 런타임 계약 준수).

    ponytail: 하루 1활동의 단순 펼침. real_breakdown 은 이미 활동 목록이라
    추가 분배가 불필요하고, 기계적 균등(critic coherence 위반)을 피한다.
    7일/12개 cap 초과분은 drop(silent-drop 경고는 빌더 진입점에서).
    """
    items = parse_real_breakdown(case.get("real_breakdown", ""))[:_MAX_TASKS]
    capped = items[:_HORIZON_DAYS]
    total = len(capped)
    days: list[dict[str, Any]] = []
    for idx, item in enumerate(capped):
        day = (today + timedelta(days=idx)).isoformat()
        days.append(
            {
                "date": day,
                "tasks": [
                    {
                        "title": item["title"],
                        "due_date": day,
                        "difficulty": _curve_difficulty(idx, total),
                    }
                ],
            }
        )
    return days


def _meta(case: dict, today: date, node: str, *, provenance: str = "daily-crawl") -> dict[str, Any]:
    return {
        "provenance": provenance,
        "node": node,
        "turn_type": "single",
        "plan_kind": case.get("plan_kind", ""),
        "today": today.isoformat(),
        "source_url": case.get("source_url", ""),
    }


def _synthetic_message(case: dict) -> str:
    slots = _slots_dict(case)
    slot_text = ", ".join(f"{k}={v}" for k, v in slots.items())
    base = case.get("goal_text") or case.get("activity") or ""
    return f"{base} ({slot_text})".strip()


def build_judge_record(case: dict, today: date) -> dict[str, Any]:
    sufficient, missing = is_daily_sufficient(case)
    parsed_goal = build_daily_parsed_goal(case, today)
    user = planner_judge_user(
        history=[], message=_synthetic_message(case), today=today, user_profile_memory=None
    )
    assistant = {
        "intent": "plan",
        "is_sufficient": sufficient,
        "missing_aspects": [] if sufficient else missing,
        "parsed_goal": _as_jsonable(parsed_goal),
    }
    return {
        "messages": [
            {"role": "system", "content": PLANNER_JUDGE_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": _meta(case, today, "judge"),
    }


def build_goal_tag_record(case: dict, today: date) -> dict[str, Any]:
    parsed_goal = build_daily_parsed_goal(case, today)
    user = goal_tag_user(parsed_goal=_as_jsonable(parsed_goal), history=[])
    assistant = {"goal_tag": parsed_goal["goal_tag"]}
    return {
        "messages": [
            {"role": "system", "content": GOAL_TAG_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": _meta(case, today, "goal_tag"),
    }


def build_generator_record(case: dict, today: date) -> dict[str, Any]:
    parsed_goal = build_daily_parsed_goal(case, today)
    user = plan_generator_user(parsed_goal=_as_jsonable(parsed_goal), today=today)
    days = build_daily_days(case, today)
    assistant = {
        "summary_text": f"'{parsed_goal['goal_text']}' 계획을 추출된 실제 활동대로 잡아뒀어요.",
        "rationale": "실제 후기에서 추출한 활동·빈도를 흐름에 맞게 배치하고 하루 부하를 분산했습니다."[:200],
        "personalization_patch": {"preferences": [], "constraints": [], "planning_style": []},
        "days": days,
    }
    return {
        "messages": [
            {"role": "system", "content": PLAN_GENERATOR_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "meta": _meta(case, today, "generator"),
    }


def _critic_parsed_goal(case: dict, today: date) -> dict[str, Any]:
    return {**build_daily_parsed_goal(case, today), "plan_kind": case.get("plan_kind", "lifestyle")}


def _critic_record(case, today, *, plan, verdict, label) -> dict[str, Any]:
    parsed_goal = _critic_parsed_goal(case, today)
    user = plan_critic_user(
        parsed_goal=_as_jsonable(parsed_goal),
        plan_json=plan,
        today=today,
        overloaded_days=_overloaded_days(plan),
    )
    meta = _meta(case, today, "critic", provenance="daily-critic")
    meta["label"] = label
    return {
        "messages": [
            {"role": "system", "content": PLAN_CRITIC_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(verdict, ensure_ascii=False)},
        ],
        "meta": meta,
    }


def _inject_offgoal(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not plan:
        return plan
    poisoned = [dict(d) for d in plan]
    first = poisoned[0]
    first_tasks = list(first["tasks"])
    first_tasks.append({"title": "기출문제 2회분", "due_date": first["date"], "difficulty": 3})
    poisoned[0] = {**first, "tasks": first_tasks}
    return poisoned


def _inject_triviality(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fillers = ["운동복·신발 확인", "기구·장비 점검", "간식·음료 정리"]
    out: list[dict[str, Any]] = []
    for idx, day in enumerate(plan):
        tasks = [{**t, "title": fillers[idx % len(fillers)]} for t in day["tasks"]]
        out.append({**day, "tasks": tasks})
    return out


def build_critic_records(case: dict, today: date) -> list[dict[str, Any]]:
    clean = build_daily_days(case, today)
    if not clean:
        return []
    positive = _critic_record(
        case, today, plan=clean, verdict={"ok": True, "issues": []}, label="positive"
    )
    offgoal = _critic_record(
        case, today, plan=_inject_offgoal(clean),
        verdict={"ok": False, "issues": [{
            "day": None, "category": "coherence", "severity": "major",
            "detail": "목표와 무관한 시험 task 가 섞여 있다.",
            "suggested_fix": "목표 도메인에 맞는 활동만 남긴다.",
        }]},
        label="offgoal",
    )
    trivial = _critic_record(
        case, today, plan=_inject_triviality(clean),
        verdict={"ok": False, "issues": [{
            "day": None, "category": "coherence", "severity": "major",
            "detail": "준비·점검·정리 같은 잡무만 있고 실체 행동이 없다.",
            "suggested_fix": "실제 활동(운동·학습 등) 단위로 바꾼다.",
        }]},
        label="triviality",
    )
    return [positive, offgoal, trivial]


def build_records(case: dict, today: date) -> list[dict[str, Any]]:
    judge = build_judge_record(case, today)
    sufficient, _ = is_daily_sufficient(case)
    if not sufficient:
        return [judge]
    return [
        judge,
        build_goal_tag_record(case, today),
        build_generator_record(case, today),
        *build_critic_records(case, today),
    ]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_daily_nodes_template.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add sft_pipeline/build/lib/daily_nodes_template.py sft_pipeline/tests/test_daily_nodes_template.py
git commit -m "feat: 일상 노드 내용 빌더 (judge 안티환각·generator real_breakdown·critic) (§4.6 Stage ②)"
```

---

### Task 7: 멀티턴 follow-up 빌더 (`build_daily_followup_sft.py`)

저정보 입력 → follow_up(질문) → 사용자 답변 → judge(충분) 멀티턴 트레이스. 봇 주도 follow_up ≤2턴(D9).

**Files:**
- Create: `sft_pipeline/build/lib/build_daily_followup_sft.py`
- Test: `sft_pipeline/tests/test_build_daily_followup_sft.py`

**Interfaces:**
- Consumes: `daily_nodes_template`(build_judge_record·build_daily_parsed_goal), `slot_schemas.slot_hints`, `planner_nodes_template.PLANNER_JUDGE_SYSTEM`
- Produces:
  - `build_multiturn_record(case: dict, *, withheld: list[str], today: date) -> dict`
  - `build_samples(structured_path: Path, today: date) -> list[dict]`

> ⚠️ **선행 확인(Step 1):** 런타임 follow_up 노드 출력의 정확한 JSON 키를 `adapters/todo_creation/_prompts.py` + `agents/todo_creation/planner/nodes/follow_up.py` 에서 읽어 미러한다(train==serve). 아래 `{kind, question, missing_aspects}` 가 실제 계약과 다르면 그 계약으로 교체.

- [ ] **Step 1: 런타임 follow_up 계약 확인**

Run: `grep -n "follow_up\|FOLLOW_UP\|missing_aspects\|question\|kind" adapters/todo_creation/_prompts.py agents/todo_creation/planner/nodes/follow_up.py`
확인 결과로 아래 테스트·구현의 follow_up assistant 스키마를 확정한다.

- [ ] **Step 2: 실패 테스트 작성**

Create `sft_pipeline/tests/test_build_daily_followup_sft.py`:
```python
import json
from datetime import date

from sft_pipeline.build.lib.build_daily_followup_sft import build_multiturn_record

TODAY = date(2026, 6, 24)


def _case():
    return {
        "source_url": "u",
        "source_type": "blog",
        "plan_kind": "routine",
        "goal_text": "꾸준히 운동",
        "activity": "헬스",
        "domains": "운동",
        "cadence": "주 3회",
        "time_of_day": "저녁",
        "horizon_days": "30",
        "trigger": "건강검진",
        "real_breakdown": "주3회 헬스|주3|저녁",
    }


def test_multiturn_asks_then_resolves():
    record = build_multiturn_record(_case(), withheld=["cadence"], today=TODAY)
    roles = [m["role"] for m in record["messages"]]
    assert roles == ["system", "user", "assistant", "user", "assistant"]
    first_assistant = json.loads(record["messages"][2]["content"])
    assert first_assistant.get("missing_aspects") == ["cadence"]
    last_assistant = json.loads(record["messages"][-1]["content"])
    assert last_assistant["is_sufficient"] is True
    assert record["meta"]["turn_type"] == "multi"
    assert record["meta"]["provenance"] == "daily-crawl"


def test_followup_capped_at_two_turns():
    record = build_multiturn_record(_case(), withheld=["activity", "cadence"], today=TODAY)
    followup_turns = [
        m for m in record["messages"]
        if m["role"] == "assistant" and "missing_aspects" in m["content"]
    ]
    assert len(followup_turns) <= 2
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest sft_pipeline/tests/test_build_daily_followup_sft.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: 구현**

Create `sft_pipeline/build/lib/build_daily_followup_sft.py`:
```python
"""저정보 일상 입력 → follow_up → 답변 → judge(충분) 멀티턴 SFT(D9: ≤2턴).

follow_up assistant 스키마는 런타임 follow_up 노드 계약을 미러한다(Step 1 확인).
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from agents.todo_creation.planner.slot_schemas import slot_hints
from sft_pipeline.build.lib.daily_nodes_template import build_judge_record
from sft_pipeline.build.lib.planner_nodes_template import PLANNER_JUDGE_SYSTEM
from sft_pipeline.io_utils import write_jsonl

_MAX_FOLLOWUPS = 2  # D9
_COL_FOR = {"activity": "activity", "cadence": "cadence", "goal": "goal_text"}


def _withhold(case: dict, withheld: list[str]) -> dict:
    blanked = dict(case)  # 불변: 새 dict
    for slot in withheld:
        blanked[_COL_FOR.get(slot, slot)] = ""
    return blanked


def build_multiturn_record(case: dict, *, withheld: list[str], today: date) -> dict[str, Any]:
    ask = withheld[:_MAX_FOLLOWUPS]
    low_info = _withhold(case, ask)
    initial_user = str(low_info.get("goal_text") or low_info.get("activity") or "계획 짜줘")

    messages: list[dict[str, str]] = [
        {"role": "system", "content": PLANNER_JUDGE_SYSTEM},
        {"role": "user", "content": initial_user},
    ]
    # follow_up 질문(여러 슬롯을 한 질문에 묶음, D9). 스키마는 Step 1 계약.
    question = " / ".join(slot_hints(case.get("plan_kind"), ask))
    messages.append({
        "role": "assistant",
        "content": json.dumps(
            {"kind": "follow_up", "question": f"{question} 알려주세요.", "missing_aspects": ask},
            ensure_ascii=False,
        ),
    })
    # 사용자 답변: 원래 슬롯 값
    answer = ", ".join(str(case.get(_COL_FOR.get(s, s), "")) for s in ask)
    messages.append({"role": "user", "content": answer})
    # 최종 judge(충분) — full case 의 judge assistant 재사용
    messages.append(build_judge_record(case, today)["messages"][-1])

    return {
        "messages": messages,
        "meta": {
            "provenance": "daily-crawl",
            "node": "judge",
            "turn_type": "multi",
            "plan_kind": case.get("plan_kind", ""),
            "today": today.isoformat(),
            "source_url": case.get("source_url", ""),
            "missing_aspects": ask,
        },
    }


def build_samples(structured_path: Path, today: date) -> list[dict]:
    with open(structured_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    samples: list[dict] = []
    for case in rows:
        if case.get("plan_kind") == "routine" and case.get("cadence"):
            samples.append(build_multiturn_record(case, withheld=["cadence"], today=today))
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="structured_daily.csv → 멀티턴 follow-up jsonl")
    parser.add_argument("structured_path", type=Path)
    parser.add_argument("out_path", type=Path)
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    samples = build_samples(args.structured_path, args.today or date.today())
    if not samples:
        raise SystemExit("[입력] 생성된 멀티턴 샘플이 0개입니다.")
    write_jsonl(samples, args.out_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_build_daily_followup_sft.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: 커밋**

```bash
git add sft_pipeline/build/lib/build_daily_followup_sft.py sft_pipeline/tests/test_build_daily_followup_sft.py
git commit -m "feat: 일상 멀티턴 follow-up SFT 빌더 (≤2턴, D9) (§4.6 Stage ②)"
```

---

### Task 8: 노드 SFT 빌더 진입점 (`build_daily_nodes_sft.py`)

structured_daily.csv → 일상 노드 jsonl. `build_planner_nodes_sft.py` 와 동형.

**Files:**
- Create: `sft_pipeline/build/lib/build_daily_nodes_sft.py`
- Test: `sft_pipeline/tests/test_build_daily_nodes_sft.py`

**Interfaces:**
- Consumes: `daily_nodes_template.build_records`, `sft_pipeline.io_utils.write_jsonl`
- Produces: `build_samples(structured_path: Path, today: date | None = None) -> list[dict]`

- [ ] **Step 1: 실패 테스트 작성**

Create `sft_pipeline/tests/test_build_daily_nodes_sft.py`:
```python
from datetime import date

from sft_pipeline.build.lib.build_daily_nodes_sft import build_samples
from sft_pipeline.structure.run_daily_structure import write_structured_daily


def test_build_samples_from_structured(tmp_path):
    raw = [{
        "source_url": "u", "source_type": "blog", "plan_kind": "루틴",
        "goal_text": "꾸준히 운동", "activity": "헬스", "domains": "운동",
        "cadence": "주 3회", "time_of_day": "저녁", "horizon": "한 달",
        "trigger": "건강검진", "real_breakdown": "주3회 헬스|주3|저녁",
    }]
    structured = tmp_path / "structured_daily.csv"
    write_structured_daily(raw, structured)
    samples = build_samples(structured, today=date(2026, 6, 24))
    assert len(samples) >= 4  # judge+goal_tag+generator+critic(3)
    assert all("messages" in s and "meta" in s for s in samples)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest sft_pipeline/tests/test_build_daily_nodes_sft.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

Create `sft_pipeline/build/lib/build_daily_nodes_sft.py`:
```python
"""structured_daily.csv → 일상 planner 노드 SFT jsonl (§4.6 Stage ②).

케이스당 judge·(goal_tag·generator·critic) 레코드. 내용은 결정론(GPT-4o 는 상류 추출만).
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from sft_pipeline.build.lib.daily_nodes_template import build_records
from sft_pipeline.io_utils import write_jsonl


def build_samples(structured_path: Path, today: date | None = None) -> list[dict]:
    today = today or date.today()
    try:
        with open(structured_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError as err:
        raise SystemExit(f"[입력] structured_daily.csv 읽기 실패: {structured_path} ({err})")
    samples: list[dict] = []
    for case in rows:
        samples.extend(build_records(case, today))
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="structured_daily.csv → 일상 노드 SFT jsonl")
    parser.add_argument("structured_path", type=Path)
    parser.add_argument("out_path", type=Path)
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    samples = build_samples(args.structured_path, today=args.today)
    if not samples:
        raise SystemExit("[입력] 생성된 샘플이 0개입니다.")
    write_jsonl(samples, args.out_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_build_daily_nodes_sft.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: 커밋**

```bash
git add sft_pipeline/build/lib/build_daily_nodes_sft.py sft_pipeline/tests/test_build_daily_nodes_sft.py
git commit -m "feat: 일상 노드 SFT 빌더 진입점 (§4.6 Stage ②)"
```

---

### Task 9: 검증 확장 — provenance 등록 + triviality 지표

`daily-crawl` provenance 를 검증·평가에 등록하고, coherence_eval 에 triviality(잡무) 자동 근사 지표를 추가한다.

**Files:**
- Modify: `sft_pipeline/build/lib/validate_dataset.py` (`PLAN_PROVENANCES` 에 `"daily-crawl"` 추가)
- Modify: `sft_pipeline/build/lib/coherence_eval.py` (triviality 지표)
- Test: `sft_pipeline/tests/test_validate.py`(확장), `sft_pipeline/tests/test_coherence_eval.py`(확장)

**Interfaces:**
- `validate_dataset.PLAN_PROVENANCES` 에 `"daily-crawl"` 추가. `daily-critic` 은 verdict 라 PLAN_PROVENANCES 밖(2층 플랜 검사 제외, 현행 유지).
- `validate_dataset._horizon_days`: `daily-crawl` → else 분기가 이미 `DAILY_HORIZON_DAYS`(7) 반환 → 변경 불요, 명시 테스트만.
- `coherence_eval._triviality_fraction(plan) -> float` + `gate3_triviality_rate` 지표.

- [ ] **Step 1: 실패 테스트 작성**

Append to `sft_pipeline/tests/test_validate.py`:
```python
def test_daily_crawl_is_plan_provenance():
    from sft_pipeline.build.lib.validate_dataset import PLAN_PROVENANCES, _horizon_days
    assert "daily-crawl" in PLAN_PROVENANCES
    assert _horizon_days({"provenance": "daily-crawl"}) == 7
```

Append to `sft_pipeline/tests/test_coherence_eval.py`:
```python
def test_triviality_metric_flags_filler_tasks():
    import json
    from sft_pipeline.build.lib.coherence_eval import _triviality_fraction
    from sft_pipeline.build.lib.plan_schemas import parse_plan
    plan = parse_plan(json.dumps({
        "summary_text": "xxxxx", "rationale": "r",
        "personalization_patch": {"preferences": [], "constraints": [], "planning_style": []},
        "days": [{"date": "2026-06-24", "tasks": [
            {"title": "운동복 확인", "due_date": "2026-06-24", "difficulty": 1},
            {"title": "기구 점검", "due_date": "2026-06-24", "difficulty": 1},
        ]}],
    }))
    assert _triviality_fraction(plan) == 1.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest sft_pipeline/tests/test_validate.py::test_daily_crawl_is_plan_provenance sft_pipeline/tests/test_coherence_eval.py::test_triviality_metric_flags_filler_tasks -v`
Expected: FAIL

- [ ] **Step 3: 구현 (validate_dataset.py)**

`PLAN_PROVENANCES` 줄을 다음으로 교체:
```python
PLAN_PROVENANCES = {"exam-crawl", "daily-latte", "exam-synth", "daily-crawl"}
```

- [ ] **Step 4: 구현 (coherence_eval.py)**

`_MECHANICAL_RE = re.compile(...)` 아래에 추가:
```python
# triviality(잡무): "확인/점검/정리/준비" 류 필러 행동(§4.6 2차 라이브 피드백).
_TRIVIAL_RE = re.compile(r"(확인|점검|정리|준비)")


def _triviality_fraction(plan) -> float:
    titles = _titles(plan)
    if not titles:
        return 0.0
    hits = sum(1 for t in titles if _TRIVIAL_RE.search(t))
    return hits / len(titles)
```
`eval_dataset` 의 plan 루프(`for s, plan in parseable:`)에 카운터를 추가한다. 루프 앞에 `triv_hits = 0` 선언, 루프 안에 `triv_hits += int(_triviality_fraction(plan) > 0.5)`, 그리고 `quantitative["plan"]` dict 에 항목 추가:
```python
            "gate3_triviality_rate": _metric(
                _rate(triv_hits, len(parseable)),
                "제목 과반이 '확인/점검/정리/준비' 류 잡무인 비율(§4.6 필러 안티패턴). 낮을수록 좋음.",
                count=triv_hits,
            ),
```

- [ ] **Step 5: 테스트 통과 확인 + 회귀**

Run: `uv run pytest sft_pipeline/tests/test_validate.py sft_pipeline/tests/test_coherence_eval.py -v`
Expected: PASS (기존 테스트 포함 전부 그린)

- [ ] **Step 6: 커밋**

```bash
git add sft_pipeline/build/lib/validate_dataset.py sft_pipeline/build/lib/coherence_eval.py sft_pipeline/tests/test_validate.py sft_pipeline/tests/test_coherence_eval.py
git commit -m "feat: daily-crawl provenance 등록 + triviality 지표 (§4.6 Stage ②)"
```

---

## Stage ③/④ — 믹스 + 학습 + eval (운영, 게이팅)

> 신규 결정론 코드가 아니라 **기존 도구를 일상 데이터로 실행**. 라이브 크롤·GPT-4o·GPU 는 외부 의존이라 키/리소스 확인 후 진행. TDD 가 아닌 명령 + 검증 체크리스트.

### Task 10: 믹스 정책 + end-to-end 스모크

**Files:**
- Modify: `sft_pipeline/build/lib/mix_dataset.py`
- Test: `sft_pipeline/tests/test_mix_dataset.py`(확장)

- [ ] **Step 1: 실패 테스트**

Append to `sft_pipeline/tests/test_mix_dataset.py`:
```python
def test_daily_crawl_excluded_from_public_until_licensed():
    from sft_pipeline.build.lib.mix_dataset import mix
    samples = [{"meta": {"provenance": "daily-crawl"}}, {"meta": {"provenance": "distractor"}}]
    public = mix(samples, release="public")
    provs = {s["meta"]["provenance"] for s in public}
    # 기본 보수(fail-closed): 라이선스 확인 전 daily-crawl 은 공개 제외.
    assert "daily-crawl" not in provs
    assert "distractor" in provs
```

- [ ] **Step 2: 라이선스 결정**

⚠️ **결정 필요:** 일상 크롤 소스 라이선스가 공개 배포 가능한지 확인(§4.6 "라이선스 명확"). 기본은 **보수적 fail-closed**(공개 제외 = `_PUBLIC_ALLOWED` 변경 없음). 위 테스트는 그 기본 정책을 고정한다. 라이선스가 공개 가능으로 확인되면 별도 커밋에서 `_PUBLIC_ALLOWED` 에 `"daily-crawl"` 추가 + 테스트 반전.

- [ ] **Step 3: 테스트 통과 확인**

Run: `uv run pytest sft_pipeline/tests/test_mix_dataset.py -v`
Expected: PASS (기존 포함 전부 그린; `_PUBLIC_ALLOWED` 무변경이라 daily-crawl 자동 제외)

- [ ] **Step 4: end-to-end 스모크 (fixture, 라이브 호출 0)**

소량 고정 `raw_daily.csv`(3~5행, 손으로 옮긴 *진짜 후기 발췌*)로:
```bash
uv run python -m sft_pipeline.structure.run_daily_structure --in fixtures/raw_daily.csv --out /tmp/structured_daily.csv
uv run python -m sft_pipeline.build.lib.build_daily_nodes_sft /tmp/structured_daily.csv /tmp/daily_nodes.jsonl --today 2026-06-24
uv run python -m sft_pipeline.build.lib.validate_dataset --in /tmp/daily_nodes.jsonl
uv run python -m sft_pipeline.build.lib.coherence_eval --in /tmp/daily_nodes.jsonl
```
Expected: validate `errors=0`; coherence `gate1_syntax_pass_rate=1.0`, positive 샘플 `gate3_triviality_rate` 낮음.

- [ ] **Step 5: 커밋**

```bash
git add sft_pipeline/tests/test_mix_dataset.py
git commit -m "test: 일상 데이터 공개 믹스 fail-closed 정책 고정 (§4.6 Stage ③)"
```

### Task 11: 혼합 학습 + 전/후 측정 (GPU·게이팅 — 별도 실행)

> GPU 필요. 코드 작업 완료 후 별도 세션/리소스에서 실행. 체크리스트만 정의.

- [ ] 라이브 크롤+추출(`run_crawl` → `daily_extractor`)으로 `raw_daily.csv` 생성, robots/ToS 준수 확인.
- [ ] `run_daily_structure` → `build_daily_nodes_sft` → `build_daily_followup_sft` 로 일상 jsonl 생성, `validate_dataset` errors=0.
- [ ] `mix_dataset` 로 **시험 + 일상 혼합**(회귀 방지, §4.6) → 학습 데이터.
- [ ] `train/train_lora.py` 로 planner LoRA 재학습.
- [ ] `scripts/live_planner_smoke.py` + `coherence_eval` 전/후 측정: 슬롯 환각·lifestyle→시험 붕괴·필러 잡무 감소 확인(메모리 `planner-live-nonexam-failures` 1·2차 결함 기준).
- [ ] `docs/features/todo/architecture.mmd` as-built 갱신(CLAUDE.md DoD).

---

## Self-Review

**1. Spec coverage (§4.6):**
- 크롤-grounded 소스 3종 → Stage ① crawl 재사용 + `daily_extractor`(blog/Q&A/공개셋은 urls.txt·source_type 으로 구분). ✅
- GPT-4o = 추출·정제만, 구조 타깃 코드 결정론 → Task 5(추출) + Task 6/8(결정론 타깃). ✅
- 추출 필드(`daily_fields.py`) + 택소노미(`daily_taxonomy.py`) → Task 1·3. ✅
- judge 안티-환각(추출 슬롯만, missing_required) → Task 6 `is_daily_sufficient`/`daily_filled_slot_keys`. ✅
- generator 목표-정합(real_breakdown 기반, content_library 아님) → Task 6 `build_daily_days`. ✅
- critic coherence + off-goal 네거티브 + triviality → Task 6 `build_critic_records` + Task 9 지표. ✅
- 멀티턴·≤2턴(D9) 유지 → Task 7. ✅
- 시험과 혼합 학습(회귀 방지) → Task 10·11 `mix_dataset`. ✅
- validate/coherence 재사용(비-시험 provenance) → Task 9. ✅
- 단계 ①→④ → Stage ①/②/③④ 구조 그대로. ✅
- 필러 잡무 안티패턴(2차 피드백) → Task 6 real_breakdown 그대로 + Task 9 triviality. ✅
- CJK 깨짐 repair → **비범위로 명시**(별도 작업 `todo-title-corruption-repair`). ✅

**2. Placeholder scan:** Task 7 follow_up 계약은 "Step 1 런타임 확인 후 확정"으로 명시 선행 단계화(추측 금지). 그 외 모든 코드 블록은 실제 구현. ✅

**3. Type consistency:** `build_records(case, today)`, `build_daily_parsed_goal`, `_meta` provenance(`daily-crawl`/`daily-critic`), `STRUCTURED_DAILY_COLUMNS`, `RAW_DAILY_COLUMNS`, `missing_required`(런타임 재사용), `_curve_difficulty`/`_overloaded_days`/`_as_jsonable`(기존 모듈 import) — Task 간 시그니처 일치. ✅

**리스크 요약:**
- (R1) **rel_day 미배선**: generator 타깃을 현 절대-날짜 계약에 맞춤. 런타임이 rel_day/allocator 로 바뀌면(Phase 2A) Task 6 generator 빌더를 그때 재정렬. 지금 rel_day 를 넣으면 train≠serve.
- (R2) **follow_up 런타임 계약 미확인**: Task 7 Step 1 에서 확인 필수. 불일치 시 그 자리에서 수정.
- (R3) **`build_daily_days` 단순 펼침**(하루 1활동): lifestyle 다중 도메인은 활동이 많아 7일/12개 cap 초과분 drop. silent-drop 경고 로그 권장(§3.5 cram 방지 정신). 정교한 분배는 후속.
- (R4) **라이선스**: 공개 배포는 Task 10 보수적 fail-closed(기본 internal).
