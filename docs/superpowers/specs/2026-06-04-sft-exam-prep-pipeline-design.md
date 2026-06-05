# SFT 시험준비 데이터셋 파이프라인 — 설계 (Design Spec)

- **작성일**: 2026-06-04
- **브랜치**: `feat/crawl-planner`
- **상태**: 승인됨 (brainstorming 단계 통과)

## 1. 목표

"단기 시험 준비 계획" 관련 실제 후기/수기를 **합법적·재현 가능하게** 수집·구조화하고, SFT(Supervised Fine-Tuning) 학습용 JSONL 데이터셋까지 생성하는 파이프라인을 구축한다.

대상 시험 (6종):

- 정보처리기사 필기
- 토익 (TOEIC)
- 한국사능력검정시험
- SQLD
- 컴활 1급
- 컴활 2급

## 2. 핵심 설계 결정 (확정)

| 결정 항목 | 선택 | 이유 |
| --- | --- | --- |
| 실행 모델 | **합법-우선 스캐폴드** | robots 강제 준수 + 차단 URL 자동 skip. mock HTML/예시 사례 포함으로 네트워크 없이 전 과정 재현. 사용자가 허용된 URL을 넣으면 실제 크롤도 가능. |
| 코드 위치 | `sft_pipeline/` (전용 최상위 디렉터리) | 기존 `agents/` 코드와 완전 분리, 독립 실행·테스트 용이. |
| 작업 브랜치 | `feat/crawl-planner` 워크트리 | FastAPI 리팩터 작업과 격리, 독립 PR 가능. |
| `output` 생성 | **템플릿 기본 + `--use-llm` 선택 재서술** | 기본은 LLM/API 키 불필요·완전 재현. 옵션으로 품질 향상. |
| 의존성 | 자체 `requirements.txt`로 분리 | 메인 `pyproject.toml` 미오염. |
| 원문 보관 | `evidence_spans`(char offset + ≤200자 인용)만 | 저작권 안전. 원문 전체는 최종 데이터셋에 미포함. |

## 3. 아키텍처

4단계 파이프라인 + 보고서 + 문서. 각 단계는 독립 CLI로 실행 가능하고, 중간 산출물(CSV/JSONL)로 느슨하게 연결된다. 네트워크 없이도 `data/mock_pages/`로 전 과정이 재현된다.

```
urls.txt ──▶ [crawl] ──▶ crawl_results.csv/.jsonl ──(사람 검수·정리)──▶ raw_cases.csv
                                                                            │
raw_cases.csv ──▶ [structure] ──▶ structured.csv ──▶ [build] ──▶ sft_dataset.jsonl ──▶ [validate]
                  (정규화·검증)                       (템플릿/LLM)                        (품질검사)
```

## 4. 디렉터리 구조

```
sft_pipeline/
├── README.md                     # 초보자용 한국어 전체 가이드
├── requirements.txt              # requests, beautifulsoup4, lxml, pyyaml, python-dotenv (openai 선택)
├── .env.example                  # OPENAI_API_KEY (LLM 옵션 시에만)
├── config/
│   ├── exam_types.yaml           # 6개 시험 표준코드 + 별칭
│   ├── extractors.yaml           # 도메인별 본문 CSS 선택자 사전 (확장 가능)
│   └── normalization.yaml        # 기간 / 하루 공부시간 정규화 규칙
├── data/
│   ├── urls.txt                  # 입력 URL 목록 (예시 포함)
│   ├── raw_cases_template.csv    # 구조화 입력 템플릿 (필드 설명 주석행 포함)
│   ├── raw_cases_sample.csv      # 12개 합성 예시 사례 (시험별 분포 + 불합격 일부)
│   ├── mock_pages/               # 오프라인 시연용 로컬 HTML + mock robots.txt
│   └── generated/                # 산출물 (.gitignore)
├── crawl/
│   ├── __init__.py
│   ├── robots.py                 # robots.txt fetch/parse, 허용여부, crawl-delay
│   ├── fetcher.py                # requests: timeout / UA / sleep / status / error
│   ├── extractor.py              # 도메인별 선택자 + fallback, title / text / length, HTML 저장 on/off
│   └── run_crawl.py              # CLI: urls.txt → crawl_results.csv/.jsonl (--mock 지원)
├── structure/
│   ├── __init__.py
│   ├── fields.py                 # 핵심 필드 dataclass + 누락값 규칙
│   ├── normalize.py              # time_left / daily_hours 정규화
│   └── run_structure.py          # CLI: raw_cases.csv → structured.csv (검증·정규화)
├── build/
│   ├── __init__.py
│   ├── templates.py              # 한국어 instruction / output 템플릿
│   ├── rephrase.py               # 선택적 LLM 재서술 (--use-llm)
│   ├── build_sft_dataset.py      # CLI: structured.csv → sft_dataset.jsonl (--variants, --split)
│   └── validate_dataset.py       # CLI: JSONL 스키마·품질 검사
├── reports/
│   ├── preprocessing_report_template.md
│   └── batch_meta_template.yaml  # 기계 판독용 메타 로그
└── tests/
    ├── test_robots.py
    ├── test_extractor.py
    ├── test_normalize.py
    ├── test_build.py
    └── test_validate.py
```

각 파일 200–400줄 목표(글로벌 코딩룰 준수), 기능/도메인별 분리.

## 5. 단계별 컴포넌트

### 5.1 crawl

- `robots.py`: 도메인 robots.txt fetch/parse, 경로별 허용 여부, crawl-delay 추출.
- `fetcher.py`: requests 기반. timeout, user-agent, 요청 간 sleep, status code, 예외 시 `error` 기록.
- `extractor.py`: 도메인별 CSS 선택자(`extractors.yaml`) 적용, 본문이 너무 짧으면 fallback 전략, `title` / `extracted_text` / `text_length` 산출, HTML 저장 on/off.
- `run_crawl.py` (CLI): `urls.txt` 입력 → 도메인별 robots 1회 확인 → **Disallow면 fetch 생략하고 `error="robots_disallow"`로 기록** → `crawl_results.csv` / `.jsonl` 출력. `--mock` 플래그로 `data/mock_pages/`를 읽어 오프라인 동작.

저장 필드: `source_url, robots_url, robots_allowed, crawl_delay, status_code, title, extracted_text, text_length, html_path, error, fetched_at`.

### 5.2 structure

- `fields.py`: 핵심 필드 dataclass + 누락값 규칙.
- `normalize.py`: 기간·시간 표현 정규화.
- `run_structure.py` (CLI): `raw_cases.csv` → 검증·정규화 → `structured.csv`.

### 5.3 build

- `templates.py`: 한국어 instruction / output 템플릿.
- `rephrase.py`: 선택적 LLM 재서술 (`--use-llm`).
- `build_sft_dataset.py` (CLI): `structured.csv` → `sft_dataset.jsonl`. 옵션 `--variants`(사례당 변형 샘플), `--split train/valid`.
- `validate_dataset.py` (CLI): 스키마·품질 검사(필수 키 존재, output 길이, 원문 복붙 휴리스틱 탐지 등).

## 6. 데이터 스키마

### 6.1 핵심 구조화 필드

`source_url, exam_type, time_left, daily_hours, start_level, goal, special_notes, actual_plan_summary, result, evidence_spans`

### 6.2 SFT 샘플 (JSONL 한 줄, 합성 예시)

```json
{
  "instruction": "다음 조건에 맞는 단기 시험 준비 계획을 세워줘.",
  "input": "시험: 정보처리기사 필기 / 남은 기간: D-7 / 하루 가용: 4시간 / 시작 수준: 비전공 노베이스 / 목표: 과목당 60점 합격 / 특이사항: 직장 병행",
  "output": "(재서술된 7일 계획 — 원문 복붙 아님)",
  "meta": {
    "source_url": "https://example.com/synthetic-case-01",
    "exam_type": "정보처리기사_필기",
    "result": "합격",
    "time_left_days": 7,
    "daily_hours": 4.0,
    "rephrased_by": "template"
  }
}
```

`meta`는 최소 `source_url, exam_type, result` 포함. 날짜·시각 필드는 ISO8601(`2026-06-04T10:00:00Z`).

### 6.3 정규화 규칙 (예)

- **기간**: `D-7 / 7일 남음 / 일주일 / 1주 → time_left_days=7`, `한 달 → 30`, `2주 → 14`.
- **하루 공부시간**: `하루 4시간 / 4h → daily_hours=4.0`, `3~5시간 → daily_hours_min/max 보존 + 대표값`.
- **누락값 정책**: 미기재 = `null`, **추정 금지**(값을 지어내지 않음), 애매 = 검수 보류 플래그.

## 7. 합법성·저작권 처리 (핵심)

- robots Disallow URL은 **수집하지 않음** (skip + 로그). 실패 요청도 전부 `error` 필드로 기록.
- `crawl_results.*`(원문 포함)는 **중간 산출물**이며 `.gitignore`. 최종 `sft_dataset.jsonl`에는 **원문 전체를 넣지 않고** 구조화 필드 + 짧은 `evidence_spans`(≤200자 인용/오프셋)만 포함.
- 동봉하는 12개 예시 사례는 실제 블로그 복제가 아니라 **6개 시험을 대표하는 합성(synthetic) 데이터**로, 안전하게 커밋·재현 가능.
- README에 광고성/협찬 글 제외 가이드 포함.

## 8. 보고서·문서·테스트

- `preprocessing_report_template.md`: 배치번호, 수집일자, 후보 수, 최종 선정 수, 제외 사유 집계, 정규화 규칙, 품질 체크리스트 + 복붙용 예시 섹션.
- `batch_meta_template.yaml`: 기계 판독용 메타 로그(배치별).
- `README.md`: 파이프라인 개요 / 파일 구조 / 처음 시작하기 / URL→크롤→구조화→JSONL 흐름 / 자주 나는 오류 / 저작권·robots·광고성 글 제외 주의 / 단기·중기·장기 계획.
- **테스트는 전부 오프라인**(mock robots/pages)로 robots 파싱·정규화·build·validate 핵심 로직 커버. 네트워크 크롤은 `--mock`으로 검증.

## 9. 향후 계획

### 단기

- 확보된 12개 사례를 실제 CSV에 입력.
- 12개 URL에 대해 robots 확인 및 추출 결과 테스트.
- 수작업 검수 후 SFT JSONL 초안 1차 생성.

### 중기

- 사례 수를 최소 50개 이상으로 확장, 시험별 균형, 불합격 사례 일부 포함.
- 정규표현식/룰 기반 추출 보조기 추가, 품질 검수 기준 고도화.

### 장기

- 반자동 라벨링 도구, 웹 UI 또는 CLI 개선.
- 데이터셋 버전 관리 체계, 평가셋(eval set) 분리, 템플릿 기반 프롬프트 다양화.

## 10. 비목표 (Out of Scope)

- 실제 네이버/티스토리 대량 크롤링(robots·JS 렌더링 제약). 사용자가 허용된 URL을 직접 공급하는 경우에만 실크롤 동작.
- 모델 학습 자체(SFT 데이터셋 생성까지가 범위).
