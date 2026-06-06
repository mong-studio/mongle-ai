# SFT 시험준비 데이터셋 파이프라인

단기 시험 준비 후기를 **합법적·재현 가능하게** 수집·구조화해 SFT(Supervised Fine-Tuning) 학습용 JSONL을 만드는 도구입니다. 대상: 정보처리기사 필기 · 토익 · 한국사능력검정 · SQLD · 컴활 1/2급.

## 전체 흐름

데이터셋은 **시험준비(exam-crawl)** 와 **일상계획(daily-latte, MS-LaTTE 유래)** 두 소스를 `{messages, meta}` 통일 포맷으로 합칩니다.

**출력 사양 (정합성 우선)**: assistant 출력은 자유 텍스트가 아니라 런타임 `agents/todo_creation/schemas.py` 의 `GenerateResult` 를 미러링한 **구조화 플랜 JSON** 입니다 — `{"summary_text": "...", "todos": [...], "calendar_events": [...]}`. 오늘 할 일은 `todos`, 미래는 `calendar_events`(C5 분기), 날짜 산술 앵커로 user 턴·meta 에 **기준일(`--today`)** 이 기록됩니다. SFT 의 학습 목표가 대화력이 아니라 **플랜의 구조·정합성**이기 때문이며, 스키마·날짜범위·분기·단조분해('N단원 풀기' 과반)는 `validate` 단계에서 기계 검증됩니다.

```
[시험] urls.txt ─[crawl]→ crawl_results.csv ─(사람 검수)→ raw_cases.csv
              ─[structure]→ structured.csv ─[build]→ exam.jsonl ┐
                                                                 ├─[mix]→ sft_dataset.jsonl ─[validate]
[일상] ms_latte.json ─[parse]→ ─[localize]→ daily_seeds.csv ─[synthesize]→ daily.jsonl ┘
```

각 단계는 독립 CLI이고 중간 CSV/JSONL로 연결됩니다. crawl 이후 단계는 동봉된 샘플 CSV로 네트워크 없이 재현할 수 있습니다.

**release 정책**: `mix --release public` 은 라이선스 없는 시험-크롤을 자동 제외하고 일상(MIT)만 공개판으로 출력합니다. `--release internal` 은 전체를 내부용으로 포함합니다.

## 파일 구조

```
sft_pipeline/
├── config/        exam_types.yaml · extractors.yaml · normalization.yaml
├── data/          urls.txt · raw_cases_*.csv · sources/(gitignore) · generated/(gitignore)
├── crawl/         robots.py · fetcher.py · extractor.py · run_crawl.py
├── structure/     exam_types.py · normalize.py · fields.py · run_structure.py
├── latte/         download.py · parse.py · localize.py · synthesize.py   # 일상(MS-LaTTE)
├── build/         templates.py · rephrase.py · build_sft_dataset.py · mix_dataset.py · validate_dataset.py
├── reports/       preprocessing_report_template.md · batch_meta_template.yaml
└── tests/
```

## 처음 시작하기

```bash
# 1) 의존성 (워크트리 루트에서)
uv sync --extra dev
uv pip install -r sft_pipeline/requirements.txt
# 주의: 이후 `uv sync`를 다시 돌리면 위 pip 설치가 사라질 수 있어 재실행 필요.

# 2) 오프라인 데모 - 동봉된 샘플 CSV로 crawl 이후 전 과정 재현 (네트워크 불필요)
uv run python -m sft_pipeline.structure.run_structure --in sft_pipeline/data/raw_cases_sample.csv --out sft_pipeline/data/generated/structured.csv
uv run python -m sft_pipeline.build.build_sft_dataset --in sft_pipeline/data/generated/structured.csv --out sft_pipeline/data/generated/sft_dataset.jsonl --today 2026-06-06
uv run python -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/sft_dataset.jsonl
```

## 실제 URL로 크롤하기

`sft_pipeline/data/urls.txt`에 URL을 한 줄씩 넣고 실행합니다. robots.txt가 차단한 URL은 자동으로 건너뛰고 `error=robots_disallow`로 기록됩니다.

```bash
uv run python -m sft_pipeline.crawl.run_crawl --urls sft_pipeline/data/urls.txt --out sft_pipeline/data/generated/crawl_results.csv --sleep 2 --timeout 10
```

크롤 결과(`crawl_results.csv`)를 **사람이 검수**해 `raw_cases.csv`로 정리합니다(원문 복붙 금지, 요약·재서술). 템플릿: `data/raw_cases_template.csv`.

## LLM 재서술 (선택)

```bash
cp .env.example .env   # 루트 .env 공용. OPENAI_API_KEY 입력
uv pip install openai
uv run python -m sft_pipeline.build.build_sft_dataset --in ... --out ... --use-llm
```
키가 없거나 호출 실패 시 자동으로 템플릿 출력으로 안전 복귀합니다.

## 일상 계획(MS-LaTTE) 데이터

플래너는 학습뿐 아니라 일상 계획도 다루므로, [MS-LaTTE](https://github.com/microsoft/MS-LaTTE)(MIT, 10,101 to-do 태스크 + 위치/시간 라벨)를 일상 시드로 사용합니다. 합성 결과는 멀티턴 대화가 아니라 **단일턴 '요청 → 구조화 플랜 JSON'** 이며, LLM 출력이 스키마·정합성 검증에 실패하면 결정론적 템플릿으로 폴백합니다.

```bash
# 1) 원본 취득(SHA 고정) → data/sources/ms_latte.json (gitignore)
uv run python -m sft_pipeline.latte.download

# 2) 파싱(다수결 집계) → 3) 한국어 라벨 현지화
G=sft_pipeline/data/generated
uv run python -m sft_pipeline.latte.parse    --in sft_pipeline/data/sources/ms_latte.json --out $G/latte_parsed.csv
uv run python -m sft_pipeline.latte.localize --in $G/latte_parsed.csv --out $G/daily_seeds.csv

# 4) 단일턴 구조화 플랜 합성. --use-llm 없으면 템플릿 폴백(오프라인). --limit 로 규모 조절.
#    --today 는 due_date 산술 기준일(재현 빌드 시 고정 권장).
uv run python -m sft_pipeline.latte.synthesize --in $G/daily_seeds.csv --out $G/daily.jsonl --limit 1000 --today 2026-06-06

# 5) 믹스 + 검증 (공개판은 시험-크롤 자동 제외)
uv run python -m sft_pipeline.build.mix_dataset --daily $G/daily.jsonl --exam $G/exam.jsonl --release internal --out $G/sft_dataset.jsonl
uv run python -m sft_pipeline.build.validate_dataset --in $G/sft_dataset.jsonl
```

**로컬 모델로 합성(외부 배포 권장)**: 외부 공개 데이터는 모델 ToS 제약을 피하려고 로컬 오픈모델을 권장합니다. OpenAI 호환 서버(Ollama/vLLM)를 띄우고 `base_url` 만 지정하면 됩니다.

```bash
# 예: Ollama (ollama serve, ollama pull qwen2.5)
export LLM_BASE_URL=http://localhost:11434/v1
uv run python -m sft_pipeline.latte.synthesize --in $G/daily_seeds.csv --out $G/daily.jsonl --limit 1000 --use-llm --model qwen2.5
```

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
| `error=robots_disallow` | 정상 동작 - robots가 막은 URL은 수집하지 않음 |

## 저작권 · robots · 광고성 글 주의

- robots.txt가 막은 URL은 **절대 수집하지 않습니다.** 실패도 전부 로그로 남깁니다.
- `data/generated/`(원문 포함)는 `.gitignore`. **최종 데이터셋엔 원문 전체를 넣지 말고** 구조화 필드 + 짧은 `evidence_spans`(≤200자)만 사용하세요.
- 협찬/광고성 후기, 학원 홍보 글은 검수 단계에서 제외하세요.
- 동봉된 `raw_cases_sample.csv`는 실제 블로그 복제가 아닌 **합성 예시**입니다.
- **배포 정책**: 시험-크롤(라이선스 없는 블로그 기반)은 **내부 학습용에만** 쓰고, 외부 공개판(`mix --release public`)에서는 자동 제외됩니다. 일상(MS-LaTTE)은 MIT라 공개 가능하나 **출처·라이선스 고지**를 유지하세요.

## 향후 계획

- **단기:** 확보 사례 12건 입력 → robots 확인·추출 테스트 → 검수 후 JSONL 초안.
- **중기:** 50건+ 확장, 시험별 균형, 불합격 사례 포함, 룰 기반 추출 보조기, 품질 기준 고도화.
- **장기:** 반자동 라벨링 도구, CLI/UI 개선, 데이터셋 버전 관리, eval set 분리, 프롬프트 다양화.
