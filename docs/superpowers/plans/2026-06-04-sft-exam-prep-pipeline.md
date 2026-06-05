# SFT 시험준비 데이터셋 파이프라인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** robots.txt를 강제 준수하는 합법-우선 스캐폴드로, URL 크롤 → 구조화 → SFT JSONL 생성 → 품질검증까지의 재현 가능한 파이프라인을 `sft_pipeline/`에 구축한다.

**Architecture:** 4단계 독립 CLI(crawl → structure → build → validate)가 중간 CSV/JSONL로 느슨하게 연결된다. 네트워크 없이 `data/mock_pages/`로 전 과정이 재현되며, 최종 데이터셋엔 원문 전체를 넣지 않고 구조화 필드 + 짧은 evidence만 담는다.

**Tech Stack:** Python 3.12, uv, pytest, requests, beautifulsoup4, lxml, pyyaml, python-dotenv, (선택) openai. 표준 `urllib.robotparser`로 robots 해석.

---

## 공통 규약 (모든 Task 적용)

- **작업 위치:** `feat/crawl-planner` 워크트리 (`/Users/jpaper/Documents/projects/mong-studio/mongle-ai-crawl-planner`).
- **테스트 실행:** 메인 `pyproject.toml`의 `addopts`가 `--cov=agents --cov-fail-under=80`을 강제하므로 **반드시 `-o addopts=""`로 덮어쓴다.** 표준 명령:
  ```bash
  uv run pytest sft_pipeline/tests/<파일> -v -o addopts=""
  ```
- **import 경로:** 루트에서 실행하므로 `from sft_pipeline.structure.normalize import ...` 형태. 각 패키지 디렉터리에 `__init__.py`(빈 파일) 필요. `sft_pipeline/__init__.py`, `sft_pipeline/tests/__init__.py`도 생성.
- **불변성:** dataclass는 가능한 `frozen=True`, 입력 인자 변경 금지(글로벌 코딩룰).
- **커밋:** 각 Task 끝에서 conventional commit으로 커밋.

---

### Task 1: 스캐폴드 디렉터리 · 의존성 · 환경 검증

**Files:**
- Create: `sft_pipeline/__init__.py` (빈 파일)
- Create: `sft_pipeline/requirements.txt`
- Create: `sft_pipeline/.env.example`
- Create: `sft_pipeline/.gitignore`
- Create: `sft_pipeline/crawl/__init__.py`, `sft_pipeline/structure/__init__.py`, `sft_pipeline/build/__init__.py`, `sft_pipeline/tests/__init__.py` (모두 빈 파일)

- [ ] **Step 1: 디렉터리와 빈 패키지 파일 생성**

```bash
cd /Users/jpaper/Documents/projects/mong-studio/mongle-ai-crawl-planner
mkdir -p sft_pipeline/{crawl,structure,build,config,reports,tests} \
         sft_pipeline/data/mock_pages/robots sft_pipeline/data/generated
touch sft_pipeline/__init__.py sft_pipeline/crawl/__init__.py \
      sft_pipeline/structure/__init__.py sft_pipeline/build/__init__.py \
      sft_pipeline/tests/__init__.py
```

- [ ] **Step 2: requirements.txt 작성**

`sft_pipeline/requirements.txt`:
```
requests>=2.31
beautifulsoup4>=4.12
lxml>=5.0
pyyaml>=6.0
python-dotenv>=1.0
# 선택: build --use-llm 사용 시에만 필요
# openai>=1.50
```

- [ ] **Step 3: .env.example 와 .gitignore 작성**

`sft_pipeline/.env.example`:
```
# build/build_sft_dataset.py --use-llm 사용 시에만 필요
OPENAI_API_KEY=sk-여기에-키-입력
OPENAI_MODEL=gpt-4o-mini
```

`sft_pipeline/.gitignore`:
```
# 크롤 원문 등 중간 산출물은 커밋하지 않는다 (저작권 안전)
data/generated/
*.pyc
__pycache__/
.env
```

- [ ] **Step 4: 의존성 설치 (pytest + 런타임 deps)**

```bash
uv sync --extra dev
uv pip install -r sft_pipeline/requirements.txt
```
주의: 이후 `uv sync`를 다시 돌리면 pip 설치분이 prune될 수 있다. 그 경우 `uv pip install -r sft_pipeline/requirements.txt`를 재실행한다. (이 주의사항은 Task 15 README에도 기록한다.)

- [ ] **Step 5: 환경 검증 — import 와 pytest 수집 확인**

```bash
uv run python -c "import requests, bs4, yaml, dotenv; print('runtime deps OK')"
uv run pytest sft_pipeline/tests -o addopts="" -q
```
Expected: `runtime deps OK` 출력. pytest는 "no tests ran" (수집 에러 없이 통과).

- [ ] **Step 6: Commit**

```bash
git add sft_pipeline/
git commit -m "chore(sft): 파이프라인 스캐폴드 디렉터리·의존성·env 추가"
```

---

### Task 2: 기간·시간 정규화 (`structure/normalize.py`)

**Files:**
- Create: `sft_pipeline/config/normalization.yaml`
- Create: `sft_pipeline/structure/normalize.py`
- Test: `sft_pipeline/tests/test_normalize.py`

- [ ] **Step 1: normalization.yaml 작성**

`sft_pipeline/config/normalization.yaml`:
```yaml
# 숫자+단위가 아닌 고정 표현 → 일(day) 매핑
time_left_keywords:
  일주일: 7
  한 주: 7
  한주: 7
  보름: 15
  반달: 15
  한 달: 30
  한달: 30
  두 달: 60
  두달: 60
# 숫자+단위 패턴에서 단위 → 일(day) 배수
period_units:
  일: 1
  주: 7
  주일: 7
  개월: 30
  달: 30
# 미기재로 간주하는 토큰 (정규화 결과 None)
missing_tokens:
  - ""
  - 미기재
  - 미상
  - 없음
  - "-"
```

- [ ] **Step 2: 실패하는 테스트 작성**

`sft_pipeline/tests/test_normalize.py`:
```python
from sft_pipeline.structure.normalize import parse_time_left, parse_daily_hours


def test_time_left_d_minus():
    assert parse_time_left("D-7").days == 7


def test_time_left_korean_keywords():
    assert parse_time_left("일주일").days == 7
    assert parse_time_left("한 달").days == 30


def test_time_left_number_unit():
    assert parse_time_left("2주").days == 14
    assert parse_time_left("10일 남음").days == 10


def test_time_left_missing_returns_none():
    assert parse_time_left("미기재").days is None
    assert parse_time_left("").days is None


def test_daily_hours_single():
    dh = parse_daily_hours("하루 4시간")
    assert dh.hours == 4.0 and dh.hours_min is None


def test_daily_hours_range():
    dh = parse_daily_hours("3~5시간")
    assert dh.hours_min == 3.0 and dh.hours_max == 5.0 and dh.hours == 4.0


def test_daily_hours_minutes():
    assert parse_daily_hours("30분").hours == 0.5


def test_daily_hours_missing():
    assert parse_daily_hours("").hours is None
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_normalize.py -v -o addopts=""
```
Expected: FAIL — `ModuleNotFoundError: No module named 'sft_pipeline.structure.normalize'`.

- [ ] **Step 4: normalize.py 구현**

`sft_pipeline/structure/normalize.py`:
```python
"""기간·하루 공부시간 표현 정규화. 추정 금지: 모호하면 None."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "normalization.yaml"


@lru_cache(maxsize=1)
def _rules() -> dict:
    with open(_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class TimeLeft:
    days: int | None
    raw: str


@dataclass(frozen=True)
class DailyHours:
    hours: float | None
    hours_min: float | None
    hours_max: float | None
    raw: str


def _is_missing(text: str) -> bool:
    return text.strip() in _rules()["missing_tokens"]


def parse_time_left(raw: str | None) -> TimeLeft:
    text = (raw or "").strip()
    if _is_missing(text):
        return TimeLeft(None, text)

    d_minus = re.search(r"[Dd]\s*-\s*(\d+)", text)
    if d_minus:
        return TimeLeft(int(d_minus.group(1)), text)

    for keyword, days in _rules()["time_left_keywords"].items():
        if keyword in text:
            return TimeLeft(int(days), text)

    units = "|".join(map(re.escape, _rules()["period_units"]))
    num_unit = re.search(rf"(\d+)\s*({units})", text)
    if num_unit:
        n = int(num_unit.group(1))
        mult = _rules()["period_units"][num_unit.group(2)]
        return TimeLeft(n * mult, text)

    return TimeLeft(None, text)


def parse_daily_hours(raw: str | None) -> DailyHours:
    text = (raw or "").strip()
    if _is_missing(text):
        return DailyHours(None, None, None, text)

    rng = re.search(r"(\d+(?:\.\d+)?)\s*[~\-]\s*(\d+(?:\.\d+)?)", text)
    if rng:
        lo, hi = float(rng.group(1)), float(rng.group(2))
        return DailyHours((lo + hi) / 2, lo, hi, text)

    minutes = re.search(r"(\d+)\s*분", text)
    if minutes:
        return DailyHours(round(int(minutes.group(1)) / 60, 2), None, None, text)

    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:시간|h|H)", text)
    if hours:
        return DailyHours(float(hours.group(1)), None, None, text)

    return DailyHours(None, None, None, text)
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_normalize.py -v -o addopts=""
```
Expected: PASS (8 passed).

- [ ] **Step 6: Commit**

```bash
git add sft_pipeline/config/normalization.yaml sft_pipeline/structure/normalize.py sft_pipeline/tests/test_normalize.py
git commit -m "feat(sft): 기간·하루시간 정규화 모듈 추가"
```

---

### Task 3: 시험종류 표준화 (`config/exam_types.yaml` + `structure/exam_types.py`)

**Files:**
- Create: `sft_pipeline/config/exam_types.yaml`
- Create: `sft_pipeline/structure/exam_types.py`
- Test: `sft_pipeline/tests/test_exam_types.py`

- [ ] **Step 1: exam_types.yaml 작성**

`sft_pipeline/config/exam_types.yaml`:
```yaml
# 표준코드: [별칭 목록]  (별칭은 소문자/공백제거 후 부분일치로 매칭)
정보처리기사_필기:
  - 정보처리기사 필기
  - 정처기 필기
  - 정처기필기
토익:
  - 토익
  - toeic
한국사능력검정시험:
  - 한국사능력검정
  - 한능검
  - 한국사
SQLD:
  - sqld
컴활1급:
  - 컴활 1급
  - 컴활1급
  - 컴퓨터활용능력 1급
  - 컴퓨터활용능력1급
컴활2급:
  - 컴활 2급
  - 컴활2급
  - 컴퓨터활용능력 2급
  - 컴퓨터활용능력2급
```

- [ ] **Step 2: 실패하는 테스트 작성**

`sft_pipeline/tests/test_exam_types.py`:
```python
from sft_pipeline.structure.exam_types import canonicalize_exam_type


def test_canonical_passthrough():
    assert canonicalize_exam_type("정보처리기사_필기") == "정보처리기사_필기"


def test_alias_match():
    assert canonicalize_exam_type("정처기 필기") == "정보처리기사_필기"
    assert canonicalize_exam_type("TOEIC") == "토익"
    assert canonicalize_exam_type("한능검") == "한국사능력검정시험"


def test_level_disambiguation():
    assert canonicalize_exam_type("컴활 1급") == "컴활1급"
    assert canonicalize_exam_type("컴활 2급") == "컴활2급"


def test_unknown_returns_none():
    assert canonicalize_exam_type("정체불명시험") is None
    assert canonicalize_exam_type("") is None
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_exam_types.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 4: exam_types.py 구현**

`sft_pipeline/structure/exam_types.py`:
```python
"""시험명 별칭 → 표준코드 변환. 매칭 실패 시 None (추정 금지)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "exam_types.yaml"


def _norm(text: str) -> str:
    return text.lower().replace(" ", "").replace("_", "")


@lru_cache(maxsize=1)
def _alias_index() -> list[tuple[str, str]]:
    with open(_CONFIG, encoding="utf-8") as f:
        mapping = yaml.safe_load(f)
    pairs: list[tuple[str, str]] = []
    for canonical, aliases in mapping.items():
        pairs.append((_norm(canonical), canonical))
        for alias in aliases:
            pairs.append((_norm(alias), canonical))
    # 중복 제거 (canonical이 별칭 목록에도 있으면 중복 생성됨), 순서 유지
    pairs = list(dict.fromkeys(pairs))
    # 긴 별칭 먼저 매칭 (컴활1급 vs 컴활)
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def canonicalize_exam_type(raw: str | None) -> str | None:
    needle = _norm(raw or "")
    if not needle:
        return None
    for alias_norm, canonical in _alias_index():
        if alias_norm == needle:
            return canonical
    return None
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_exam_types.py -v -o addopts=""
```
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add sft_pipeline/config/exam_types.yaml sft_pipeline/structure/exam_types.py sft_pipeline/tests/test_exam_types.py
git commit -m "feat(sft): 시험종류 표준화 모듈 추가"
```

---

### Task 4: 구조화 필드 스키마·검증 (`structure/fields.py`)

**Files:**
- Create: `sft_pipeline/structure/fields.py`
- Test: `sft_pipeline/tests/test_fields.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`sft_pipeline/tests/test_fields.py`:
```python
from sft_pipeline.structure.fields import RAW_COLUMNS, structure_row


def _row(**overrides):
    base = {c: "" for c in RAW_COLUMNS}
    base.update(
        source_url="https://example.com/case-1",
        exam_type="정처기 필기",
        time_left="D-7",
        daily_hours="하루 4시간",
        start_level="비전공 노베이스",
        goal="과목당 60점 합격",
        special_notes="직장 병행",
        actual_plan_summary="기출 3회독 + 오답정리",
        result="합격",
    )
    base.update(overrides)
    return base


def test_structure_row_happy_path():
    case = structure_row(_row())
    assert case.exam_type == "정보처리기사_필기"
    assert case.time_left_days == 7
    assert case.daily_hours_value == 4.0
    assert case.result == "합격"
    assert case.review_flags == []


def test_unknown_exam_type_flagged():
    case = structure_row(_row(exam_type="정체불명"))
    assert case.exam_type == ""
    assert "exam_type_unmapped" in case.review_flags


def test_missing_time_left_flagged_not_guessed():
    case = structure_row(_row(time_left=""))
    assert case.time_left_days is None
    assert "time_left_missing" in case.review_flags


def test_invalid_result_normalized_to_unknown():
    case = structure_row(_row(result="음.."))
    assert case.result == "미상"
    assert "result_unknown" in case.review_flags
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_fields.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 3: fields.py 구현**

`sft_pipeline/structure/fields.py`:
```python
"""구조화 케이스 스키마. 누락값 정책: 미기재→빈값/None, 추정 금지, 모호→review_flags."""
from __future__ import annotations

from dataclasses import dataclass, field

from sft_pipeline.structure.exam_types import canonicalize_exam_type
from sft_pipeline.structure.normalize import parse_daily_hours, parse_time_left

RAW_COLUMNS = [
    "source_url",
    "exam_type",
    "time_left",
    "daily_hours",
    "start_level",
    "goal",
    "special_notes",
    "actual_plan_summary",
    "result",
    "evidence_spans",
]

VALID_RESULTS = {"합격", "불합격"}


@dataclass(frozen=True)
class StructuredCase:
    source_url: str
    exam_type: str
    time_left: str
    time_left_days: int | None
    daily_hours: str
    daily_hours_value: float | None
    daily_hours_min: float | None
    daily_hours_max: float | None
    start_level: str
    goal: str
    special_notes: str
    actual_plan_summary: str
    result: str
    evidence_spans: str
    review_flags: list[str] = field(default_factory=list)


def structure_row(row: dict) -> StructuredCase:
    flags: list[str] = []

    exam = canonicalize_exam_type(row.get("exam_type", ""))
    if exam is None:
        flags.append("exam_type_unmapped")
        exam = ""

    tl = parse_time_left(row.get("time_left", ""))
    if tl.days is None:
        flags.append("time_left_missing")

    dh = parse_daily_hours(row.get("daily_hours", ""))
    if dh.hours is None:
        flags.append("daily_hours_missing")

    result = (row.get("result", "") or "").strip()
    if result not in VALID_RESULTS:
        flags.append("result_unknown")
        result = "미상"

    if not (row.get("actual_plan_summary", "") or "").strip():
        flags.append("plan_summary_missing")

    return StructuredCase(
        source_url=(row.get("source_url", "") or "").strip(),
        exam_type=exam,
        time_left=tl.raw,
        time_left_days=tl.days,
        daily_hours=dh.raw,
        daily_hours_value=dh.hours,
        daily_hours_min=dh.hours_min,
        daily_hours_max=dh.hours_max,
        start_level=(row.get("start_level", "") or "").strip(),
        goal=(row.get("goal", "") or "").strip(),
        special_notes=(row.get("special_notes", "") or "").strip(),
        actual_plan_summary=(row.get("actual_plan_summary", "") or "").strip(),
        result=result,
        evidence_spans=(row.get("evidence_spans", "") or "").strip(),
        review_flags=flags,
    )
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_fields.py -v -o addopts=""
```
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add sft_pipeline/structure/fields.py sft_pipeline/tests/test_fields.py
git commit -m "feat(sft): 구조화 필드 스키마·검증 추가"
```

---

### Task 5: 구조화 CLI · 입력 템플릿 · 합성 샘플 (`structure/run_structure.py`)

**Files:**
- Create: `sft_pipeline/structure/run_structure.py`
- Create: `sft_pipeline/data/raw_cases_template.csv`
- Create: `sft_pipeline/data/raw_cases_sample.csv`
- Test: `sft_pipeline/tests/test_run_structure.py`

- [ ] **Step 1: raw_cases_template.csv 작성 (필드 설명 주석행 포함)**

`sft_pipeline/data/raw_cases_template.csv`:
```csv
source_url,exam_type,time_left,daily_hours,start_level,goal,special_notes,actual_plan_summary,result,evidence_spans
# source_url: 출처 URL | exam_type: 시험명(별칭 허용) | time_left: D-7/일주일/2주 등 | daily_hours: 하루 4시간/3~5시간 등 | start_level: 시작 수준 | goal: 목표 | special_notes: 특이사항 | actual_plan_summary: 실제 계획 요약(원문 복붙 금지, 재서술) | result: 합격/불합격 | evidence_spans: 근거 짧은 인용(<=200자) 또는 offset
```
주의: `#`로 시작하는 행은 CLI가 주석으로 건너뛴다.

- [ ] **Step 2: 합성 샘플 12건 작성**

`sft_pipeline/data/raw_cases_sample.csv` (실제 블로그 복제 아님 — 6개 시험 대표 합성 데이터, 불합격 2건 포함):
```csv
source_url,exam_type,time_left,daily_hours,start_level,goal,special_notes,actual_plan_summary,result,evidence_spans
https://example.com/case-01,정처기 필기,D-7,하루 4시간,비전공 노베이스,과목당 60점 합격,직장 병행,기출 5개년 3회독 후 오답만 반복 정리,합격,기출 위주로 돌렸다
https://example.com/case-02,정보처리기사 필기,2주,3~5시간,비전공,평균 70점,주말 집중,개념 1회독 후 기출 위주 정리 및 약점 과목 보충,합격,개념은 가볍게
https://example.com/case-03,토익,D-14,하루 3시간,500점대,750점,LC 약점,파트별 문제풀이 루틴화 + 단어 매일 50개,합격,단어가 핵심
https://example.com/case-04,toeic,10일 남음,2시간,600점대,700점,직장인,실전 모의 5회분 + 오답 분석 집중,불합격,시간이 부족했다
https://example.com/case-05,한능검,일주일,하루 5시간,노베이스,심화 1급,벼락치기,흐름 강의 1회독 + 기출 3회분 반복,합격,흐름부터 잡았다
https://example.com/case-06,한국사,D-5,4시간,노베이스,3급,주말 활용,핵심 키워드 암기 + 기출 2회분,합격,키워드 암기
https://example.com/case-07,SQLD,2주,하루 2시간,비전공,합격,개념 약함,노랭이 문제집 2회독 + SQL 구문 정리,합격,노랭이 반복
https://example.com/case-08,sqld,D-10,3시간,데이터 입문,합격,,핵심 이론 정리 후 기출 유형별 반복,불합격,2과목을 놓쳤다
https://example.com/case-09,컴활 1급,3주,하루 3시간,엑셀 중급,필기 합격,함수 약점,필기 기출 반복 + 자주 나오는 함수 정리,합격,함수 위주
https://example.com/case-10,컴활1급,D-14,2시간,초급,실기 합격,,실기 기출 함수·매크로 반복 숙달,합격,매크로 연습
https://example.com/case-11,컴활 2급,일주일,하루 2시간,노베이스,필기 합격,,기출 2회독으로 빠르게 정리,합격,이틀이면 충분
https://example.com/case-12,컴활2급,D-3,3시간,초급,실기 합격,단기,실기 기출 유형 집중 반복,합격,유형만 외웠다
```

- [ ] **Step 3: 실패하는 테스트 작성**

`sft_pipeline/tests/test_run_structure.py`:
```python
import csv
from pathlib import Path

from sft_pipeline.structure.run_structure import read_raw_cases, write_structured

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "raw_cases_sample.csv"


def test_read_skips_comment_rows():
    rows = read_raw_cases(SAMPLE)
    assert len(rows) == 12
    assert all(not r["source_url"].startswith("#") for r in rows)


def test_write_structured_roundtrip(tmp_path):
    rows = read_raw_cases(SAMPLE)
    out = tmp_path / "structured.csv"
    write_structured(rows, out)
    with open(out, encoding="utf-8") as f:
        result = list(csv.DictReader(f))
    assert len(result) == 12
    assert result[0]["exam_type"] == "정보처리기사_필기"
    assert result[0]["time_left_days"] == "7"
    # 불합격 사례 포함 확인
    assert any(r["result"] == "불합격" for r in result)
```

- [ ] **Step 4: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_run_structure.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 5: run_structure.py 구현**

`sft_pipeline/structure/run_structure.py`:
```python
"""raw_cases.csv → structured.csv (검증·정규화). #로 시작하는 행은 주석."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sft_pipeline.structure.fields import StructuredCase, structure_row

STRUCTURED_COLUMNS = [
    "source_url",
    "exam_type",
    "time_left",
    "time_left_days",
    "daily_hours",
    "daily_hours_value",
    "daily_hours_min",
    "daily_hours_max",
    "start_level",
    "goal",
    "special_notes",
    "actual_plan_summary",
    "result",
    "evidence_spans",
    "review_flags",
]


def read_raw_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            row
            for row in reader
            if row.get("source_url") and not row["source_url"].lstrip().startswith("#")
        ]


def _to_record(case: StructuredCase) -> dict:
    return {
        "source_url": case.source_url,
        "exam_type": case.exam_type,
        "time_left": case.time_left,
        "time_left_days": "" if case.time_left_days is None else case.time_left_days,
        "daily_hours": case.daily_hours,
        "daily_hours_value": "" if case.daily_hours_value is None else case.daily_hours_value,
        "daily_hours_min": "" if case.daily_hours_min is None else case.daily_hours_min,
        "daily_hours_max": "" if case.daily_hours_max is None else case.daily_hours_max,
        "start_level": case.start_level,
        "goal": case.goal,
        "special_notes": case.special_notes,
        "actual_plan_summary": case.actual_plan_summary,
        "result": case.result,
        "evidence_spans": case.evidence_spans,
        "review_flags": ";".join(case.review_flags),
    }


def write_structured(rows: list[dict], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records = [_to_record(structure_row(r)) for r in rows]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STRUCTURED_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="raw_cases.csv → structured.csv")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()
    rows = read_raw_cases(args.in_path)
    n = write_structured(rows, args.out_path)
    print(f"structured {n} cases -> {args.out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 테스트 통과 + CLI 수동 실행 확인**

```bash
uv run pytest sft_pipeline/tests/test_run_structure.py -v -o addopts=""
uv run python -m sft_pipeline.structure.run_structure \
  --in sft_pipeline/data/raw_cases_sample.csv \
  --out sft_pipeline/data/generated/structured.csv
```
Expected: 테스트 PASS (2 passed). CLI는 `structured 12 cases -> ...` 출력.

- [ ] **Step 7: Commit**

```bash
git add sft_pipeline/structure/run_structure.py sft_pipeline/data/raw_cases_template.csv sft_pipeline/data/raw_cases_sample.csv sft_pipeline/tests/test_run_structure.py
git commit -m "feat(sft): 구조화 CLI·입력 템플릿·합성 샘플 12건 추가"
```

---

### Task 6: robots 평가 (`crawl/robots.py`)

**Files:**
- Create: `sft_pipeline/crawl/robots.py`
- Test: `sft_pipeline/tests/test_robots.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`sft_pipeline/tests/test_robots.py`:
```python
from sft_pipeline.crawl.robots import evaluate, robots_url_for

ROBOTS = """
User-agent: *
Disallow: /private/
Crawl-delay: 3
"""


def test_robots_url_for():
    assert robots_url_for("https://blog.example.com/post/1") == "https://blog.example.com/robots.txt"


def test_allowed_path():
    info = evaluate("https://blog.example.com/post/1", "mybot", robots_text=ROBOTS)
    assert info.allowed is True
    assert info.crawl_delay == 3.0


def test_disallowed_path():
    info = evaluate("https://blog.example.com/private/x", "mybot", robots_text=ROBOTS)
    assert info.allowed is False


def test_empty_robots_allows_all():
    info = evaluate("https://blog.example.com/post/1", "mybot", robots_text="")
    assert info.allowed is True
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_robots.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 3: robots.py 구현**

`sft_pipeline/crawl/robots.py`:
```python
"""표준 urllib.robotparser 기반 robots 평가. 순수 함수(robots_text 주입)로 테스트 용이."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser


@dataclass(frozen=True)
class RobotsInfo:
    robots_url: str
    allowed: bool
    crawl_delay: float | None


def robots_url_for(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def evaluate(url: str, user_agent: str, *, robots_text: str) -> RobotsInfo:
    parser = RobotFileParser()
    parser.parse((robots_text or "").splitlines())
    allowed = parser.can_fetch(user_agent, url)
    delay = parser.crawl_delay(user_agent)
    return RobotsInfo(
        robots_url=robots_url_for(url),
        allowed=allowed,
        crawl_delay=float(delay) if delay is not None else None,
    )
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_robots.py -v -o addopts=""
```
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add sft_pipeline/crawl/robots.py sft_pipeline/tests/test_robots.py
git commit -m "feat(sft): robots 평가 모듈 추가"
```

---

### Task 7: 본문 추출 (`crawl/extractor.py`)

**Files:**
- Create: `sft_pipeline/config/extractors.yaml`
- Create: `sft_pipeline/crawl/extractor.py`
- Test: `sft_pipeline/tests/test_extractor.py`

- [ ] **Step 1: extractors.yaml 작성**

`sft_pipeline/config/extractors.yaml`:
```yaml
# 도메인 → 본문 CSS 선택자 우선순위. 와일드카드는 접미사 매칭(*.tistory.com).
default:
  - article
  - main
  - "#content"
"blog.naver.com":
  - "div.se-main-container"
  - "#postViewArea"
"*.tistory.com":
  - ".entry-content"
  - ".article_view"
"example.com":
  - "article.post"
# 본문 최소 길이(글자). 미만이면 fallback 단계로.
min_length: 50
```

- [ ] **Step 2: 실패하는 테스트 작성**

`sft_pipeline/tests/test_extractor.py`:
```python
from sft_pipeline.crawl.extractor import extract

HTML = """
<html><head><title>합격 후기</title></head>
<body><article class="post"><p>기출 3회독 했습니다.</p><p>오답 정리가 핵심.</p></article></body></html>
"""

SHORT_HTML = "<html><head><title>짧음</title></head><body><div>짧</div></body></html>"


def test_extract_uses_domain_selector():
    res = extract(HTML, "https://example.com/case-1")
    assert res.title == "합격 후기"
    assert "기출 3회독" in res.text
    assert res.text_length == len(res.text)
    assert res.used_selector == "article.post"


def test_extract_fallback_when_short():
    res = extract(SHORT_HTML, "https://unknown-domain.com/x")
    assert res.used_selector == "fallback"
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_extractor.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 4: extractor.py 구현**

`sft_pipeline/crawl/extractor.py`:
```python
"""도메인별 선택자 + fallback 본문 추출. bs4 사용."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from bs4 import BeautifulSoup

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "extractors.yaml"


@lru_cache(maxsize=1)
def _config() -> dict:
    with open(_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class Extracted:
    title: str
    text: str
    text_length: int
    used_selector: str


def _selectors_for(domain: str) -> list[str]:
    cfg = _config()
    # exact-domain keys must precede wildcard keys in extractors.yaml to take priority
    for key, selectors in cfg.items():
        if key in ("default", "min_length"):
            continue
        if key.startswith("*.") and domain.endswith(key[1:]):
            return selectors
        if key == domain:
            return selectors
    return cfg["default"]


def _title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""


def extract(html: str, url: str) -> Extracted:
    if not html:
        return Extracted("", "", 0, "fallback")
    soup = BeautifulSoup(html, "lxml")
    domain = urlsplit(url).netloc
    min_length = _config()["min_length"]
    title = _title(soup)

    for selector in _selectors_for(domain):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(separator="\n", strip=True)
            if len(text) >= min_length:
                return Extracted(title, text, len(text), selector)

    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    text = "\n".join(filter(None, paragraphs))
    if not text:
        body = soup.find("body")
        text = body.get_text(separator="\n", strip=True) if body else ""
    return Extracted(title, text, len(text), "fallback")
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_extractor.py -v -o addopts=""
```
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add sft_pipeline/config/extractors.yaml sft_pipeline/crawl/extractor.py sft_pipeline/tests/test_extractor.py
git commit -m "feat(sft): 도메인별 본문 추출 모듈 추가"
```

---

### Task 8: HTTP fetcher (`crawl/fetcher.py`)

**Files:**
- Create: `sft_pipeline/crawl/fetcher.py`
- Test: `sft_pipeline/tests/test_fetcher.py`

- [ ] **Step 1: 실패하는 테스트 작성 (네트워크 없이 fake session)**

`sft_pipeline/tests/test_fetcher.py`:
```python
from sft_pipeline.crawl.fetcher import FetchResult, fetch


class _Resp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _OkSession:
    def get(self, url, timeout, headers):
        return _Resp(200, "<html><title>ok</title></html>")


class _BoomSession:
    def get(self, url, timeout, headers):
        raise RuntimeError("connection refused")


def test_fetch_success():
    res = fetch("https://example.com/a", session=_OkSession(), timeout=5, user_agent="bot")
    assert isinstance(res, FetchResult)
    assert res.status_code == 200
    assert "ok" in res.html
    assert res.error is None


def test_fetch_records_error():
    res = fetch("https://example.com/a", session=_BoomSession(), timeout=5, user_agent="bot")
    assert res.html is None
    assert res.status_code is None
    assert "connection refused" in res.error
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_fetcher.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 3: fetcher.py 구현**

`sft_pipeline/crawl/fetcher.py`:
```python
"""requests 기반 단일 페이지 fetch. 예외는 error 필드로 흡수(실패도 로그로 남김)."""
from __future__ import annotations

from dataclasses import dataclass

import requests

DEFAULT_USER_AGENT = "mongle-sft-crawler/0.1 (+research; respects robots.txt)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int | None
    html: str | None
    error: str | None


def fetch(
    url: str,
    *,
    session=None,
    timeout: float = 10.0,
    user_agent: str = DEFAULT_USER_AGENT,
) -> FetchResult:
    sess = session or requests.Session()
    try:
        resp = sess.get(url, timeout=timeout, headers={"User-Agent": user_agent})
        return FetchResult(url, resp.status_code, resp.text, None)
    except Exception as exc:  # noqa: BLE001 - 실패도 기록해야 함
        return FetchResult(url, None, None, f"{type(exc).__name__}: {exc}")
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_fetcher.py -v -o addopts=""
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add sft_pipeline/crawl/fetcher.py sft_pipeline/tests/test_fetcher.py
git commit -m "feat(sft): HTTP fetcher 모듈 추가(실패도 기록)"
```

---

### Task 9: 크롤 오케스트레이션 CLI + mock 자산 (`crawl/run_crawl.py`)

**Files:**
- Create: `sft_pipeline/crawl/run_crawl.py`
- Create: `sft_pipeline/data/urls.txt`
- Create: `sft_pipeline/data/mock_pages/case-01.html`
- Create: `sft_pipeline/data/mock_pages/secret.html` (생성하지 않음 — robots로 차단되어 fetch 자체를 안 함. 아래 설명 참고)
- Create: `sft_pipeline/data/mock_pages/robots/example.com.txt`
- Test: `sft_pipeline/tests/test_run_crawl.py`

> 참고: `/private/secret`은 robots Disallow로 차단되므로 mock 페이지 파일을 만들 필요가 없다(fetch 단계 도달 전에 skip). 따라서 mock html은 `case-01.html` 하나만 만든다.

- [ ] **Step 1: urls.txt 와 mock 자산 작성**

`sft_pipeline/data/urls.txt`:
```
# 한 줄에 URL 하나. #로 시작하면 주석. --mock 실행 시 경로 마지막 조각(slug)으로 mock_pages를 찾는다.
https://example.com/case-01
https://example.com/private/secret
```

`sft_pipeline/data/mock_pages/case-01.html`:
```html
<html><head><title>정처기 필기 7일 합격 후기</title></head>
<body><article class="post">
<p>비전공이지만 기출 5개년을 3회독 했습니다.</p>
<p>오답만 모아 반복하니 과목당 60점을 넘겼습니다.</p>
</article></body></html>
```

`sft_pipeline/data/mock_pages/robots/example.com.txt`:
```
User-agent: *
Disallow: /private/
Crawl-delay: 0
```

- [ ] **Step 2: 실패하는 테스트 작성**

`sft_pipeline/tests/test_run_crawl.py`:
```python
import csv
from pathlib import Path

from sft_pipeline.crawl.run_crawl import run

DATA = Path(__file__).resolve().parent.parent / "data"


def test_mock_crawl_blocks_disallowed(tmp_path):
    out = tmp_path / "crawl_results.csv"
    rows = run(
        urls_path=DATA / "urls.txt",
        out_csv=out,
        mock=True,
        user_agent="mybot",
    )
    by_url = {r["source_url"]: r for r in rows}

    allowed = by_url["https://example.com/case-01"]
    assert allowed["robots_allowed"] == "True"
    assert allowed["error"] == ""
    assert "기출" in allowed["extracted_text"]
    assert int(allowed["text_length"]) > 0

    blocked = by_url["https://example.com/private/secret"]
    assert blocked["robots_allowed"] == "False"
    assert blocked["error"] == "robots_disallow"
    assert blocked["extracted_text"] == ""

    # CSV로도 기록되는지
    with open(out, encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 2
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_run_crawl.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 4: run_crawl.py 구현**

`sft_pipeline/crawl/run_crawl.py`:
```python
"""urls.txt → crawl_results.csv/.jsonl. robots 차단 URL은 fetch 생략하고 기록."""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from sft_pipeline.crawl.extractor import extract
from sft_pipeline.crawl.fetcher import DEFAULT_USER_AGENT, fetch
from sft_pipeline.crawl.robots import evaluate, robots_url_for

RESULT_COLUMNS = [
    "source_url",
    "robots_url",
    "robots_allowed",
    "crawl_delay",
    "status_code",
    "title",
    "extracted_text",
    "text_length",
    "html_path",
    "error",
    "fetched_at",
]

_MOCK_DIR = Path(__file__).resolve().parent.parent / "data" / "mock_pages"


def read_urls(path: Path) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.lstrip().startswith("#")
        ]


def _mock_slug(url: str) -> str:
    last = urlsplit(url).path.rstrip("/").split("/")[-1] or "index"
    return last


def _load_mock_robots(url: str) -> str:
    domain = urlsplit(url).netloc
    path = _MOCK_DIR / "robots" / f"{domain}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _load_mock_page(url: str) -> tuple[int, str | None, str | None]:
    path = _MOCK_DIR / f"{_mock_slug(url)}.html"
    if path.exists():
        return 200, path.read_text(encoding="utf-8"), None
    return 404, None, "mock_page_not_found"


def _now() -> str:
    # 결정성을 위해 고정 타임스탬프(테스트·재현 친화). 실제 시각이 필요하면 호출측에서 갱신.
    return "1970-01-01T00:00:00Z"


def _empty_row(url: str, robots_url: str) -> dict:
    return {c: "" for c in RESULT_COLUMNS} | {
        "source_url": url,
        "robots_url": robots_url,
        "fetched_at": _now(),
    }


def _effective_delay(sleep: float, crawl_delay) -> float:
    try:
        declared = float(crawl_delay)
    except (TypeError, ValueError):
        declared = 0.0
    return max(sleep, declared)


def _crawl_one(
    url: str,
    *,
    user_agent: str,
    mock: bool,
    session,
    timeout: float,
    robots_cache: dict[str, str] | None = None,
) -> dict:
    row = _empty_row(url, robots_url_for(url))

    if mock:
        robots_text = _load_mock_robots(url)
    else:
        domain = urlsplit(url).netloc
        if robots_cache is None:
            robots_cache = {}
        if domain not in robots_cache:
            robots_cache[domain] = _fetch_robots(url, session, timeout, user_agent)
        robots_text = robots_cache[domain]

    info = evaluate(url, user_agent, robots_text=robots_text)
    row["robots_allowed"] = str(info.allowed)
    row["crawl_delay"] = "" if info.crawl_delay is None else info.crawl_delay

    if not info.allowed:
        row["error"] = "robots_disallow"
        return row

    if mock:
        status, html, error = _load_mock_page(url)
    else:
        result = fetch(url, session=session, timeout=timeout, user_agent=user_agent)
        status, html, error = result.status_code, result.html, result.error

    row["status_code"] = "" if status is None else status
    if error:
        row["error"] = error
        return row

    if status is not None and status >= 400:
        row["error"] = f"http_{status}"
        return row

    extracted = extract(html, url)
    row["title"] = extracted.title
    row["extracted_text"] = extracted.text
    row["text_length"] = extracted.text_length
    return row


def _fetch_robots(url: str, session, timeout: float, user_agent: str) -> str:
    result = fetch(robots_url_for(url), session=session, timeout=timeout, user_agent=user_agent)
    return result.html or ""


def run(
    *,
    urls_path: Path,
    out_csv: Path,
    mock: bool = False,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 10.0,
    sleep: float = 1.0,
) -> list[dict]:
    session = None if mock else requests.Session()
    urls = read_urls(urls_path)
    robots_cache: dict[str, str] = {}
    rows: list[dict] = []
    for i, url in enumerate(urls):
        row = _crawl_one(url, user_agent=user_agent, mock=mock, session=session, timeout=timeout, robots_cache=robots_cache)
        rows.append(row)
        if not mock and i + 1 < len(urls):
            time.sleep(_effective_delay(sleep, row["crawl_delay"]))

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    out_jsonl = out_csv.with_suffix(".jsonl")
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="urls.txt → crawl_results.csv/.jsonl")
    parser.add_argument("--urls", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="crawl_results.csv 경로")
    parser.add_argument("--mock", action="store_true", help="data/mock_pages 사용(오프라인)")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()
    rows = run(
        urls_path=args.urls,
        out_csv=args.out,
        mock=args.mock,
        user_agent=args.user_agent,
        timeout=args.timeout,
        sleep=args.sleep,
    )
    blocked = sum(1 for r in rows if r["error"] == "robots_disallow")
    print(f"crawled {len(rows)} urls ({blocked} robots-blocked) -> {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 테스트 통과 + CLI 수동 실행 확인**

```bash
uv run pytest sft_pipeline/tests/test_run_crawl.py -v -o addopts=""
uv run python -m sft_pipeline.crawl.run_crawl \
  --urls sft_pipeline/data/urls.txt \
  --out sft_pipeline/data/generated/crawl_results.csv --mock
```
Expected: 테스트 PASS (1 passed). CLI는 `crawled 2 urls (1 robots-blocked) -> ...` 출력.

- [ ] **Step 6: Commit**

```bash
git add sft_pipeline/crawl/run_crawl.py sft_pipeline/data/urls.txt sft_pipeline/data/mock_pages/
git add sft_pipeline/tests/test_run_crawl.py
git commit -m "feat(sft): 크롤 오케스트레이션 CLI + mock 자산 추가"
```

---

### Task 10: SFT 텍스트 템플릿 (`build/templates.py`)

**Files:**
- Create: `sft_pipeline/build/templates.py`
- Test: `sft_pipeline/tests/test_templates.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`sft_pipeline/tests/test_templates.py`:
```python
from sft_pipeline.build.templates import build_input, build_instruction, build_output


CASE = {
    "exam_type": "정보처리기사_필기",
    "time_left": "D-7",
    "time_left_days": "7",
    "daily_hours": "하루 4시간",
    "start_level": "비전공 노베이스",
    "goal": "과목당 60점 합격",
    "special_notes": "직장 병행",
    "actual_plan_summary": "기출 5개년 3회독 후 오답 정리",
    "result": "합격",
}


def test_build_input_contains_fields():
    text = build_input(CASE)
    assert "정보처리기사_필기" in text
    assert "D-7" in text
    assert "하루 4시간" in text


def test_build_instruction_nonempty():
    assert len(build_instruction(CASE)) > 0


def test_build_output_reframes_not_rawcopy():
    out = build_output(CASE)
    assert "기출 5개년 3회독" in out  # 계획 요약 반영
    assert out != CASE["actual_plan_summary"]  # 단순 복붙 아님
    assert "정보처리기사_필기" in out
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_templates.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 3: templates.py 구현**

`sft_pipeline/build/templates.py`:
```python
"""구조화 필드 → instruction/input/output 한국어 텍스트. output은 재서술(복붙 아님)."""
from __future__ import annotations


def _field(case: dict, key: str, default: str = "미기재") -> str:
    value = (case.get(key) or "").strip()
    return value or default


def build_instruction(case: dict) -> str:
    return "다음 조건에 맞는 단기 시험 준비 계획을 세워줘."


def build_input(case: dict) -> str:
    return (
        f"시험: {_field(case, 'exam_type')} / "
        f"남은 기간: {_field(case, 'time_left')} / "
        f"하루 가용: {_field(case, 'daily_hours')} / "
        f"시작 수준: {_field(case, 'start_level')} / "
        f"목표: {_field(case, 'goal')} / "
        f"특이사항: {_field(case, 'special_notes')}"
    )


def build_output(case: dict) -> str:
    exam = _field(case, "exam_type")
    period = _field(case, "time_left")
    daily = _field(case, "daily_hours")
    level = _field(case, "start_level")
    goal = _field(case, "goal")
    summary = _field(case, "actual_plan_summary", default="")
    notes = _field(case, "special_notes", default="")

    lines = [
        f"[{exam} · {period} · {daily} 준비 플랜]",
        f"시작 수준 {level} 기준으로 '{goal}'을(를) 목표로 잡습니다.",
        "",
        "추천 학습 흐름:",
        f"- {summary}" if summary else "- (계획 요약 미기재)",
    ]
    if notes:
        lines.append(f"핵심 유의점: {notes} 상황을 고려해 무리한 분량보다 반복에 집중하세요.")
    return "\n".join(lines)
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_templates.py -v -o addopts=""
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add sft_pipeline/build/templates.py sft_pipeline/tests/test_templates.py
git commit -m "feat(sft): SFT 텍스트 템플릿 추가"
```

---

### Task 11: 선택적 LLM 재서술 (`build/rephrase.py`)

**Files:**
- Create: `sft_pipeline/build/rephrase.py`
- Test: `sft_pipeline/tests/test_rephrase.py`

- [ ] **Step 1: 실패하는 테스트 작성 (LLM 호출 없이 fake client)**

`sft_pipeline/tests/test_rephrase.py`:
```python
from sft_pipeline.build.rephrase import rephrase


def test_template_default_no_llm():
    text, by = rephrase("원본 계획 텍스트", use_llm=False)
    assert text == "원본 계획 텍스트"
    assert by == "template"


class _FakeClient:
    class chat:
        class completions:
            @staticmethod
            def create(model, messages):
                class _M:
                    content = "재서술된 계획"

                class _C:
                    message = _M()

                class _R:
                    choices = [_C()]

                return _R()


def test_llm_path_uses_client():
    text, by = rephrase("원본", use_llm=True, client=_FakeClient(), model="x")
    assert text == "재서술된 계획"
    assert by == "llm"


class _BoomClient:
    class chat:
        class completions:
            @staticmethod
            def create(model, messages):
                raise RuntimeError("rate limit")


def test_llm_error_falls_back_to_template():
    text, by = rephrase("원본", use_llm=True, client=_BoomClient(), model="x")
    assert text == "원본"
    assert by == "template"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_rephrase.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 3: rephrase.py 구현**

`sft_pipeline/build/rephrase.py`:
```python
"""선택적 LLM 재서술. 기본은 템플릿 그대로. 실패 시 템플릿 fallback(재현성 보장)."""
from __future__ import annotations

_SYSTEM = "너는 시험 준비 계획을 자연스럽고 간결하게 한국어로 다듬는 도우미다. 사실을 추가하지 말고 표현만 정리해라."


def rephrase(
    text: str,
    *,
    use_llm: bool = False,
    client=None,
    model: str = "gpt-4o-mini",
) -> tuple[str, str]:
    if not use_llm or client is None:
        return text, "template"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text},
            ],
        )
        return resp.choices[0].message.content, "llm"
    except Exception:  # noqa: BLE001 - LLM 실패 시 결정적 템플릿으로 안전 복귀
        return text, "template"


def make_client():
    """OPENAI_API_KEY가 있으면 openai 클라이언트 생성, 없으면 None."""
    import os

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    from openai import OpenAI

    return OpenAI(api_key=key)
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_rephrase.py -v -o addopts=""
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add sft_pipeline/build/rephrase.py sft_pipeline/tests/test_rephrase.py
git commit -m "feat(sft): 선택적 LLM 재서술 모듈 추가"
```

---

### Task 12: SFT 데이터셋 빌더 CLI (`build/build_sft_dataset.py`)

**Files:**
- Create: `sft_pipeline/build/build_sft_dataset.py`
- Test: `sft_pipeline/tests/test_build_sft_dataset.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`sft_pipeline/tests/test_build_sft_dataset.py`:
```python
import json
from pathlib import Path

from sft_pipeline.build.build_sft_dataset import build_samples, write_jsonl


def _structured_csv(tmp_path: Path) -> Path:
    import csv

    from sft_pipeline.structure.run_structure import STRUCTURED_COLUMNS

    path = tmp_path / "structured.csv"
    row = {c: "" for c in STRUCTURED_COLUMNS}
    row.update(
        source_url="https://example.com/case-1",
        exam_type="정보처리기사_필기",
        time_left="D-7",
        time_left_days="7",
        daily_hours="하루 4시간",
        daily_hours_value="4.0",
        start_level="비전공",
        goal="합격",
        actual_plan_summary="기출 3회독",
        result="합격",
    )
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STRUCTURED_COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    return path


def test_build_samples_schema(tmp_path):
    samples = build_samples(_structured_csv(tmp_path))
    assert len(samples) == 1
    s = samples[0]
    assert set(s) == {"instruction", "input", "output", "meta"}
    assert s["meta"]["source_url"] == "https://example.com/case-1"
    assert s["meta"]["exam_type"] == "정보처리기사_필기"
    assert s["meta"]["result"] == "합격"
    assert s["meta"]["rephrased_by"] == "template"


def test_write_jsonl(tmp_path):
    samples = build_samples(_structured_csv(tmp_path))
    out = tmp_path / "sft.jsonl"
    write_jsonl(samples, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["meta"]["exam_type"] == "정보처리기사_필기"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_build_sft_dataset.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 3: build_sft_dataset.py 구현**

`sft_pipeline/build/build_sft_dataset.py`:
```python
"""structured.csv → sft_dataset.jsonl. --use-llm/--split 옵션 지원."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sft_pipeline.build.rephrase import make_client, rephrase
from sft_pipeline.build.templates import build_input, build_instruction, build_output


def _to_float(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_int(value):
    if value in ("", None):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def build_samples(
    structured_path: Path,
    *,
    use_llm: bool = False,
    client=None,
    model: str = "gpt-4o-mini",
) -> list[dict]:
    with open(structured_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    samples: list[dict] = []
    for case in rows:
        output, by = rephrase(build_output(case), use_llm=use_llm, client=client, model=model)
        samples.append(
            {
                "instruction": build_instruction(case),
                "input": build_input(case),
                "output": output,
                "meta": {
                    "source_url": case.get("source_url", ""),
                    "exam_type": case.get("exam_type", ""),
                    "result": case.get("result", ""),
                    "time_left_days": _to_int(case.get("time_left_days", "")),
                    "daily_hours": _to_float(case.get("daily_hours_value", "")),
                    "rephrased_by": by,
                },
            }
        )
    return samples


def write_jsonl(samples: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def _split(samples: list[dict], ratio: float = 0.8) -> tuple[list[dict], list[dict]]:
    cut = max(1, int(len(samples) * ratio))
    return samples[:cut], samples[cut:]


def main() -> None:
    parser = argparse.ArgumentParser(description="structured.csv → sft_dataset.jsonl")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--split", action="store_true", help="train/valid 분리 출력(8:2)")
    args = parser.parse_args()

    client = make_client() if args.use_llm else None
    if args.use_llm and client is None:
        print("warning: --use-llm 지정됐지만 OPENAI_API_KEY 가 없어 템플릿으로 대체합니다.", file=sys.stderr)
    samples = build_samples(args.in_path, use_llm=args.use_llm, client=client)

    if args.split:
        train, valid = _split(samples)
        if not valid:
            print("warning: 샘플이 너무 적어 valid 세트가 비었습니다.", file=sys.stderr)
        write_jsonl(train, args.out_path.with_name(args.out_path.stem + "_train.jsonl"))
        write_jsonl(valid, args.out_path.with_name(args.out_path.stem + "_valid.jsonl"))
        print(f"wrote {len(train)} train / {len(valid)} valid")
    else:
        write_jsonl(samples, args.out_path)
        print(f"wrote {len(samples)} samples -> {args.out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_build_sft_dataset.py -v -o addopts=""
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add sft_pipeline/build/build_sft_dataset.py sft_pipeline/tests/test_build_sft_dataset.py
git commit -m "feat(sft): SFT 데이터셋 빌더 CLI 추가"
```

---

### Task 13: 데이터셋 검증 CLI (`build/validate_dataset.py`)

**Files:**
- Create: `sft_pipeline/build/validate_dataset.py`
- Test: `sft_pipeline/tests/test_validate.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`sft_pipeline/tests/test_validate.py`:
```python
import json
from pathlib import Path

from sft_pipeline.build.validate_dataset import validate_samples


def _write(tmp_path: Path, samples: list[dict]) -> Path:
    path = tmp_path / "ds.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return path


def _good():
    return {
        "instruction": "다음 조건에 맞는 단기 시험 준비 계획을 세워줘.",
        "input": "시험: 토익 / 남은 기간: D-7",
        "output": "[토익 · D-7 준비 플랜]\n추천 학습 흐름: 매일 모의고사 1회분",
        "meta": {"source_url": "https://example.com/1", "exam_type": "토익", "result": "합격"},
    }


def test_valid_sample_passes(tmp_path):
    report = validate_samples(_write(tmp_path, [_good()]))
    assert report["ok"] == 1
    assert report["errors"] == []


def test_missing_key_flagged(tmp_path):
    bad = _good()
    del bad["output"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("output" in e for e in report["errors"])


def test_raw_copy_flagged(tmp_path):
    bad = _good()
    bad["output"] = bad["input"]  # input 그대로 복붙
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("raw_copy" in e for e in report["errors"])
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest sft_pipeline/tests/test_validate.py -v -o addopts=""
```
Expected: FAIL — module not found.

- [ ] **Step 3: validate_dataset.py 구현**

`sft_pipeline/build/validate_dataset.py`:
```python
"""SFT JSONL 품질 검사. 스키마·빈값·input 복붙(output==input) 휴리스틱.

참고: 이 검증기는 '데이터셋 위생'(스키마/빈값/프롬프트 복붙)만 본다.
원문(블로그) 표절 방지는 상류 단계의 책임이다 — actual_plan_summary 는
사람이 재서술한 요약이어야 하며(원문 복붙 금지), 이는 수집 검수 체크리스트
(reports/preprocessing_report_template.md)와 README 가이드로 강제한다.
build_output 은 의도적으로 actual_plan_summary 를 템플릿에 포함하므로,
output 이 요약을 포함하는지 검사하지 않는다(정상 동작을 오탐하게 됨).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_KEYS = {"instruction", "input", "output", "meta"}
REQUIRED_META = {"source_url", "exam_type", "result"}
MIN_OUTPUT_LEN = 20


def _validate_one(sample: dict, idx: int) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_KEYS - set(sample)
    if missing:
        errors.append(f"line {idx}: missing keys {sorted(missing)}")
        return errors

    for key in ("instruction", "input", "output"):
        if not str(sample[key]).strip():
            errors.append(f"line {idx}: empty {key}")

    meta = sample.get("meta") or {}
    meta_missing = REQUIRED_META - set(meta)
    if meta_missing:
        errors.append(f"line {idx}: meta missing {sorted(meta_missing)}")

    output = str(sample.get("output", ""))
    if len(output.strip()) < MIN_OUTPUT_LEN:
        errors.append(f"line {idx}: output too short (<{MIN_OUTPUT_LEN})")
    if output.strip() and output.strip() == str(sample.get("input", "")).strip():
        errors.append(f"line {idx}: raw_copy (output == input)")
    return errors


def validate_samples(path: Path) -> dict:
    errors: list[str] = []
    ok = 0
    with open(path, encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {idx}: invalid json ({exc})")
                continue
            line_errors = _validate_one(sample, idx)
            if line_errors:
                errors.extend(line_errors)
            else:
                ok += 1
    return {"ok": ok, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description="SFT JSONL 품질 검사")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    args = parser.parse_args()
    report = validate_samples(args.in_path)
    print(f"ok={report['ok']} errors={len(report['errors'])}")
    for err in report["errors"]:
        print(f"  - {err}")
    sys.exit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests/test_validate.py -v -o addopts=""
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add sft_pipeline/build/validate_dataset.py sft_pipeline/tests/test_validate.py
git commit -m "feat(sft): 데이터셋 품질 검증 CLI 추가"
```

---

### Task 14: 전처리 보고서 템플릿 (`reports/`)

**Files:**
- Create: `sft_pipeline/reports/preprocessing_report_template.md`
- Create: `sft_pipeline/reports/batch_meta_template.yaml`

- [ ] **Step 1: preprocessing_report_template.md 작성**

`sft_pipeline/reports/preprocessing_report_template.md`:
```markdown
# 전처리 배치 보고서 — 배치 #<NN>

- **수집 일자:** YYYY-MM-DD
- **담당자:** <이름>
- **대상 시험:** <예: 토익, SQLD>

## 1. 수집 요약

| 항목 | 수 |
| --- | --- |
| 수집 후보 URL | 0 |
| robots 차단 제외 | 0 |
| 본문 추출 실패 | 0 |
| 광고/협찬 제외 | 0 |
| 최종 선정 | 0 |

## 2. 제외 사유 집계

| 사유 | 건수 | 비고 |
| --- | --- | --- |
| robots_disallow | 0 | |
| 본문 < min_length | 0 | |
| 광고성/협찬 | 0 | |
| 중복 | 0 | |

## 3. 적용한 정규화 규칙

- 기간: D-7 / 일주일 / 2주 → time_left_days
- 하루 시간: 하루 4시간 / 3~5시간 → daily_hours_value(+min/max)
- 누락값: 미기재→공란, 추정 금지, 모호→review_flags

## 4. 품질 점검 체크리스트

- [ ] exam_type 표준코드로 매핑됨 (review_flags에 exam_type_unmapped 없음)
- [ ] time_left/daily_hours 정규화 값 확인
- [ ] result 합격/불합격 정확
- [ ] actual_plan_summary 원문 복붙 아님(재서술)
- [ ] evidence_spans ≤200자
- [ ] validate_dataset.py errors=0

## 5. 메모 / 다음 배치 이월 사항

- ...
```

- [ ] **Step 2: batch_meta_template.yaml 작성**

`sft_pipeline/reports/batch_meta_template.yaml`:
```yaml
batch: 0
collected_date: "YYYY-MM-DD"
owner: ""
exams: []
counts:
  candidates: 0
  robots_blocked: 0
  extract_failed: 0
  ad_excluded: 0
  selected: 0
normalization:
  time_left: "D-7/일주일/2주 -> days"
  daily_hours: "하루4시간/3~5시간 -> value(+min/max)"
quality:
  validate_errors: 0
  exam_type_unmapped: 0
notes: ""
```

- [ ] **Step 3: Commit**

```bash
git add sft_pipeline/reports/
git commit -m "docs(sft): 전처리 보고서 md/yaml 템플릿 추가"
```

---

### Task 15: 초보자용 README (`sft_pipeline/README.md`)

**Files:**
- Create: `sft_pipeline/README.md`

- [ ] **Step 1: README 작성**

`sft_pipeline/README.md`:
````markdown
# SFT 시험준비 데이터셋 파이프라인

단기 시험 준비 후기를 **합법적·재현 가능하게** 수집·구조화해 SFT(Supervised Fine-Tuning) 학습용 JSONL을 만드는 도구입니다. 대상: 정보처리기사 필기 · 토익 · 한국사능력검정 · SQLD · 컴활 1/2급.

## 전체 흐름

```
urls.txt ─[crawl]→ crawl_results.csv ─(사람 검수)→ raw_cases.csv
        ─[structure]→ structured.csv ─[build]→ sft_dataset.jsonl ─[validate]
```

각 단계는 독립 CLI이고 중간 CSV/JSONL로 연결됩니다. **네트워크 없이 `--mock`으로 전 과정을 재현**할 수 있습니다.

## 파일 구조

```
sft_pipeline/
├── config/        exam_types.yaml · extractors.yaml · normalization.yaml
├── data/          urls.txt · raw_cases_template.csv · raw_cases_sample.csv · mock_pages/ · generated/(gitignore)
├── crawl/         robots.py · fetcher.py · extractor.py · run_crawl.py
├── structure/     exam_types.py · normalize.py · fields.py · run_structure.py
├── build/         templates.py · rephrase.py · build_sft_dataset.py · validate_dataset.py
├── reports/       preprocessing_report_template.md · batch_meta_template.yaml
└── tests/
```

## 처음 시작하기

```bash
# 1) 의존성 (워크트리 루트에서)
uv sync --extra dev
uv pip install -r sft_pipeline/requirements.txt
# 주의: 이후 `uv sync`를 다시 돌리면 위 pip 설치가 사라질 수 있어 재실행 필요.

# 2) 오프라인 데모 (mock) — 네트워크 불필요
uv run python -m sft_pipeline.crawl.run_crawl --urls sft_pipeline/data/urls.txt --out sft_pipeline/data/generated/crawl_results.csv --mock
uv run python -m sft_pipeline.structure.run_structure --in sft_pipeline/data/raw_cases_sample.csv --out sft_pipeline/data/generated/structured.csv
uv run python -m sft_pipeline.build.build_sft_dataset --in sft_pipeline/data/generated/structured.csv --out sft_pipeline/data/generated/sft_dataset.jsonl
uv run python -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/sft_dataset.jsonl
```

## 실제 URL로 크롤하기

`sft_pipeline/data/urls.txt`에 URL을 한 줄씩 넣고 `--mock` 없이 실행합니다. robots.txt가 차단한 URL은 자동으로 건너뛰고 `error=robots_disallow`로 기록됩니다.

```bash
uv run python -m sft_pipeline.crawl.run_crawl --urls sft_pipeline/data/urls.txt --out sft_pipeline/data/generated/crawl_results.csv --sleep 2 --timeout 10
```

크롤 결과(`crawl_results.csv`)를 **사람이 검수**해 `raw_cases.csv`로 정리합니다(원문 복붙 금지, 요약·재서술). 템플릿: `data/raw_cases_template.csv`.

## LLM 재서술 (선택)

```bash
cp sft_pipeline/.env.example sft_pipeline/.env   # OPENAI_API_KEY 입력
uv pip install openai
uv run python -m sft_pipeline.build.build_sft_dataset --in ... --out ... --use-llm
```
키가 없거나 호출 실패 시 자동으로 템플릿 출력으로 안전 복귀합니다.

## 테스트

```bash
uv run pytest sft_pipeline/tests -o addopts="" -q
```
메인 `pyproject.toml`의 커버리지 게이트(`--cov=agents`) 때문에 **`-o addopts=""`가 필수**입니다.

## 자주 나는 오류

| 증상 | 원인 / 해결 |
| --- | --- |
| `ModuleNotFoundError: bs4/yaml/requests` | `uv pip install -r sft_pipeline/requirements.txt` 재실행 |
| `No module named pytest` | `uv sync --extra dev` |
| pytest가 coverage로 실패 | `-o addopts=""` 빠짐 |
| 크롤 결과 본문 비어 있음 | JS 렌더링 페이지. `config/extractors.yaml`에 도메인 선택자 추가 또는 제외 |
| `error=robots_disallow` | 정상 동작 — robots가 막은 URL은 수집하지 않음 |

## 저작권 · robots · 광고성 글 주의

- robots.txt가 막은 URL은 **절대 수집하지 않습니다.** 실패도 전부 로그로 남깁니다.
- `data/generated/`(원문 포함)는 `.gitignore`. **최종 데이터셋엔 원문 전체를 넣지 말고** 구조화 필드 + 짧은 `evidence_spans`(≤200자)만 사용하세요.
- 협찬/광고성 후기, 학원 홍보 글은 검수 단계에서 제외하세요.
- 동봉된 `raw_cases_sample.csv`는 실제 블로그 복제가 아닌 **합성 예시**입니다.

## 향후 계획

- **단기:** 확보 사례 12건 입력 → robots 확인·추출 테스트 → 검수 후 JSONL 초안.
- **중기:** 50건+ 확장, 시험별 균형, 불합격 사례 포함, 룰 기반 추출 보조기, 품질 기준 고도화.
- **장기:** 반자동 라벨링 도구, CLI/UI 개선, 데이터셋 버전 관리, eval set 분리, 프롬프트 다양화.
````

- [ ] **Step 2: Commit**

```bash
git add sft_pipeline/README.md
git commit -m "docs(sft): 초보자용 README 추가"
```

---

### Task 16: 전체 통합 스모크 + 전체 테스트 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md` (최상단에 항목 추가)
- Test: 전체 `sft_pipeline/tests`

- [ ] **Step 1: 전체 테스트 통과 확인**

```bash
uv run pytest sft_pipeline/tests -o addopts="" -q
```
Expected: 모든 테스트 PASS (약 28 passed), 실패·에러 0.

- [ ] **Step 2: end-to-end 스모크 실행 (mock → structure → build → validate)**

```bash
uv run python -m sft_pipeline.crawl.run_crawl --urls sft_pipeline/data/urls.txt --out sft_pipeline/data/generated/crawl_results.csv --mock
uv run python -m sft_pipeline.structure.run_structure --in sft_pipeline/data/raw_cases_sample.csv --out sft_pipeline/data/generated/structured.csv
uv run python -m sft_pipeline.build.build_sft_dataset --in sft_pipeline/data/generated/structured.csv --out sft_pipeline/data/generated/sft_dataset.jsonl
uv run python -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/sft_dataset.jsonl
```
Expected: 마지막 명령이 `ok=12 errors=0` 출력하고 종료코드 0. (`data/generated/`는 gitignore되어 커밋 대상 아님.)

- [ ] **Step 3: CHANGELOG.md 최상단에 항목 추가**

`CHANGELOG.md` 최상단(기존 첫 항목 위)에 삽입:
```markdown
## sft_pipeline 추가 (2026-06-04)

- 합법-우선 SFT 데이터셋 파이프라인 `sft_pipeline/` 신설.
- crawl(robots 강제 준수·실패 로그) → structure(정규화·검증) → build(템플릿/선택적 LLM) → validate 4단계 CLI.
- 오프라인 `--mock` 재현, 합성 샘플 12건, 전처리 보고서 템플릿, 초보자 README 포함.
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(sft): CHANGELOG에 파이프라인 추가 기록"
```

---

## Self-Review (작성자 체크 완료)

**Spec coverage:** 2단계 크롤(robots/fetcher/extractor/run_crawl, 도메인 선택자 dict, fallback, HTML 저장 옵션은 mock_pages 경로로 단순화) → Task 6–9. 3단계 구조화(10개 핵심 필드, 누락값 규칙, 기간·시간 정규화) → Task 2–5. 4단계 SFT(instruction/input/output/meta, 재서술, --split/--use-llm, validate) → Task 10–13. 5단계 보고서(md+yaml) → Task 14. 6단계 문서 → Task 15. 7단계 향후계획 → README + spec §9. 모든 spec 섹션에 대응 Task 존재.

**Placeholder scan:** "TBD/TODO/적절히 처리" 없음. 모든 코드 스텝에 실제 코드 포함.

**Type consistency:** `STRUCTURED_COLUMNS`(run_structure)는 Task 12 테스트에서 import해 재사용. `RAW_COLUMNS`/`structure_row`/`StructuredCase`(fields)는 Task 4·5 일관. `evaluate`/`RobotsInfo`/`robots_url_for`(robots)는 Task 6·9 일관. `fetch`/`FetchResult`/`DEFAULT_USER_AGENT`(fetcher)는 Task 8·9 일관. `extract`/`Extracted`(extractor)는 Task 7·9 일관. `build_input`/`build_instruction`/`build_output`은 Task 10·12 일관. `rephrase`/`make_client`는 Task 11·12 일관.

**알려진 단순화(YAGNI):** spec의 "HTML 저장 on/off", "--variants"는 핵심 흐름에 불필요해 기본 범위에서 제외(README/spec에 옵션으로 남김). 필요 시 후속 Task로 추가.
