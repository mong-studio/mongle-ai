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
├── build/         templates.py · rephrase.py · build_sft_dataset.py · distractor.py · mix_dataset.py · validate_dataset.py
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

## distractor(네거티브) 데이터

플랜만 학습하면 모델이 잡담·거절·되묻기 상황에도 플랜 JSON을 토해냅니다. 이를 막기 위해 **"플랜을 만들면 안 되는 경계 사례"**(잡담/감사, 과약속 거절, 모호한 의도 되묻기, 프롬프트 인젝션 방어, 범위 밖·위험 요청 거절 등)를 일정 비율 섞습니다.

- distractor 의 assistant 출력은 **평문 대화**라 `meta.provenance="distractor"` 로 표시되며, `validate` 2층(플랜 정합성)을 건너뛰고 **1층(형식 위생)만** 받습니다.
- distractor 는 우리가 만든 데이터(저작권 이슈 없음)라 **공개판에도 포함**됩니다(`_PUBLIC_ALLOWED`).
- `mix` 가 distractor 를 플랜 샘플 사이에 **균등 인터리브**(끝에 몰리지 않게)합니다.

```bash
# 1) 원본(network 불필요, 외부 파일) → SFT 포맷으로 유형 비율 보존 30% 서브샘플
uv run python -m sft_pipeline.build.distractor --in path/to/mongle_distractor_v2.jsonl --out $G/distractor.jsonl --fraction 0.30

# 2) 플랜(daily/exam) + distractor 믹스 (distractor 는 균등 인터리브됨)
uv run python -m sft_pipeline.build.mix_dataset \
  --daily $G/daily.jsonl --exam $G/exam.jsonl --distractor $G/distractor.jsonl \
  --release internal --out $G/sft_dataset.jsonl
uv run python -m sft_pipeline.build.validate_dataset --in $G/sft_dataset.jsonl
```

권장 비율은 **약 30%**(일상 1000건 기준 distractor ≈ 300건)입니다. 너무 높으면 과생성을 막는 대신 모델이 과도하게 거절(과거절)할 수 있습니다.

## RunPod 본생성 (Docker 올인원)

대규모(1000건+) 합성은 GPU가 필요해 **RunPod GPU Pod**에서 돌립니다. `sft_pipeline/docker/` 의 올인원 이미지가 한 컨테이너에서 **vLLM(Qwen 서빙) + 합성 + S3 업로드**를 모두 수행합니다. 엔트리포인트(`run_synthesis.sh`)가 `vLLM 기동 → /health 대기 → download → parse → localize → synthesize → S3 업로드` 를 자동 실행합니다.

이미지는 GitHub Actions(`.github/workflows/sft-docker.yml`)가 GHCR로 빌드·푸시합니다 → `ghcr.io/mong-studio/mongle-ai/sft-synthesis`. (수동 빌드: `docker build -f sft_pipeline/docker/Dockerfile -t sft-synthesis .`)

### 실행 절차

1. **GPU Pod 생성** — 14B 기준 **A100 40GB**(또는 L40S). 컨테이너 이미지에 위 GHCR 태그 지정.
2. **환경변수 설정** (RunPod Pod의 Environment Variables):

   | 변수 | 기본값 | 설명 |
   | --- | --- | --- |
   | `MODEL` | `Qwen/Qwen2.5-14B-Instruct` | 서빙·합성 모델(HF에서 런타임 다운로드) |
   | `SAMPLE_LIMIT` | `1000` | 합성할 시드 수 |
   | `REQUEST_TIMEOUT` | `60` | 단일 LLM 요청 타임아웃(초) |
   | `TODAY` | (빈값=오늘) | due_date 기준일. **재현 빌드 시 `YYYY-MM-DD` 고정 권장** |
   | `S3_BUCKET` | (없으면 업로드 생략) | 산출물 업로드 버킷 |
   | `S3_PREFIX` | `sft/daily` | 업로드 키 prefix |
   | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | — | AWS 자격증명(시크릿) |
   | `GPU_MEMORY_UTILIZATION` | `0.90` | vLLM VRAM 사용률 |
   | `MAX_MODEL_LEN` | `8192` | vLLM 최대 컨텍스트 |

3. Pod가 시작되면 자동으로 전 과정을 수행하고 `s3://$S3_BUCKET/$S3_PREFIX/daily.jsonl` 로 업로드합니다. `S3_BUCKET` 미설정 시 컨테이너 볼륨의 `data/generated/daily.jsonl` 에 남으니 수동 회수하세요.

> 합성은 한 줄씩 증분 기록(flush)되고 요청 타임아웃이 걸려 있어, 중간에 Pod가 죽어도 진행분은 보존됩니다.
>
> 작업이 끝나면 컨테이너는 종료하지 않고 대기 상태로 들어갑니다. RunPod이 컨테이너 종료를 재시작으로 받아들여 합성을 처음부터 다시 돌리고 결과물을 덮어쓰는 것을 막기 위함입니다. vLLM도 계속 떠 있으니, 같은 Pod에 `exec`로 접속해 exam-synth 같은 후속 작업을 바로 이어서 돌릴 수 있습니다. 다 끝나면 Pod를 직접 STOP 하세요. (업로드가 실패해도 결과물은 컨테이너 안에 남으며, 권한·버킷을 고친 뒤 다시 올리면 됩니다.)

## 파인튜닝 파이프라인 (exam-synth → distractor → mix → split → train)

데이터가 모이면 아래 순서로 **풀 믹스 → 층화 분할 → LoRA 학습**까지 잇습니다.

### 1. exam-synth 합성 (RunPod GPU)

같은 Pod에 `exec`로 접속해 합성합니다(teacher = 14B). 예시 그라운딩용 `exam.jsonl`이 있으면 `--exemplars`로 넘기고, 없으면 생략해도 됩니다(내장 few-shot).

```bash
python3 -m sft_pipeline.build.exam_synth \
  --out $G/exam_synth.jsonl \
  --total 1000 --use-llm --model Qwen/Qwen2.5-14B-Instruct \
  --exemplars exam.jsonl --exemplar-n 2 --concurrency 16
```

### 2. distractor 서브샘플 (네거티브)

원본 distractor를 30% 층화 서브샘플 + provenance 태깅합니다(원본을 mix에 직접 넣지 말 것 — 태깅 안 된 1000건 전부 들어갑니다).

```bash
uv run python -m sft_pipeline.build.distractor \
  --in path/to/mongle_distractor_v2.jsonl --out $G/distractor.jsonl --fraction 0.30
```

### 3. 풀 믹스

```bash
uv run python -m sft_pipeline.build.mix_dataset \
  --exam $G/exam.jsonl --exam-synth $G/exam_synth.jsonl \
  --daily $G/daily.jsonl --distractor $G/distractor.jsonl \
  --release internal --out $G/sft_dataset.jsonl
```

> distractor 비율: 30% 서브샘플(≈300)은 **일상 1000건 기준**으로 잡은 값입니다. exam-synth 1000건이 더해지면 전체 대비 네거티브 비중이 ≈13%로 희석되니, 더 높은 네거티브 비율을 원하면 `--fraction`을 올리세요.

### 4. 층화 셔플/분할

provenance(시험/일상/distractor)별 비율을 보존하며 셔플 후 train/valid로 나눕니다. 내용 SHA256 dedup으로 train↔valid 누수를 막습니다.

```bash
uv run python -m sft_pipeline.build.split_dataset \
  --in $G/sft_dataset.jsonl \
  --out-train $G/sft_train.jsonl --out-valid $G/sft_valid.jsonl \
  --ratio 0.9 --seed 42
```

### 5. LoRA 학습 (unsloth, Qwen2.5-7B)

제품 서빙 모델(7B)을 LoRA 파인튜닝합니다(student). 토큰화·마스킹·EOS·responses-only loss는 unsloth/trl에 위임합니다. RunPod PyTorch 템플릿에서:

```bash
pip install "unsloth[colab-new]" trl peft accelerate bitsandbytes datasets
python -m sft_pipeline.train.train_lora \
  --train $G/sft_train.jsonl --valid $G/sft_valid.jsonl \
  --out outputs/qwen7b-planner-lora --epochs 2 --lr 2e-4
```

학습 후 점검(sft-coherence phase 6): validation loss 확인(0.2 미만이면 과적합 경고), EOS 스모크 테스트, 생성물을 `plan_schemas.parse_plan`으로 파싱해 성공률 측정.

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
