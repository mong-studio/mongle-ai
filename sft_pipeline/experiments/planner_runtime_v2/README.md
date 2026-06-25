# Planner Runtime V2 RunPod 실험

기존 서비스 어댑터 `bigmooon/qwen2.5-7b-mongle-planner-ko-lora`는 유지한다.
신규 데이터, 출력 디렉터리, Hugging Face 저장소를 모두 `runtime-v2` 이름으로 분리해
평가를 통과한 뒤에만 RunPod Serverless 환경변수를 바꾼다.

## 폴더 구성

```text
sft_pipeline/experiments/planner_runtime_v2/
├── README.md                         # RunPod 실행·배포·롤백 절차
├── build_dataset.py                  # 300건 결정론적 생성기
├── data/
│   └── planner_runtime_v2_gold_300.jsonl
├── train_runpod.sh                   # 격리 학습 진입점
├── evaluate.py                       # 학습된 V2 어댑터 승격 평가
├── planner_ab_test.ipynb             # 기존 모델과 V2 대화 비교
└── tests/test_dataset.py             # 데이터 재현성·스키마 검사
```

학습 엔진과 공통 validator는 기존 `sft_pipeline/train/`과 `sft_pipeline/build/lib/`를
읽기 전용으로 재사용한다. 기존 데이터와 어댑터 출력 경로는 수정하거나 덮어쓰지 않는다.

## 1. 실험 경계

| 구분 | 기존 | 신규 실험 |
|---|---|---|
| 출력 스키마 | `kind/phases` 혼재 | `summary_text/personalization_patch/days` |
| 학습 데이터 | 기존 IPE/daily 데이터 | `planner_runtime_v2_gold_300.jsonl`만 사용 |
| 로컬 출력 | 기존 경로 유지 | `outputs/planner-runtime-v2-*` |
| HF 저장소 | 기존 repo 유지 | 새 `...planner-runtime-v2` repo |
| 서비스 전환 | 현재 env 유지 | 평가 통과 뒤 `LORA_PLANNER_REPO`만 변경 |

기존 `daily_gold.jsonl`, `distractor_gold.jsonl`, `ipe_hardened_v4_*.jsonl`은 현재
런타임 출력 계약과 다르므로 신규 실험에 섞지 않는다. 요청 분류와 플랜 검증은 Base
모델이 담당하고, 이 LoRA는 정보가 모인 뒤의 플랜 생성만 학습한다.

## 2. RunPod 준비

- RTX 4090 24GB 이상 권장
- PyTorch CUDA Pod, 컨테이너 디스크 40GB 이상
- 현재 작업 브랜치를 commit/push한 뒤 RunPod에서 clone
- 비공개 Hugging Face 사용 시 `HF_TOKEN` 준비

```bash
cd /workspace
git clone <REPOSITORY_URL> mongle-ai
cd mongle-ai
git checkout <BRANCH>
```

학습 전 데이터만 다시 만들고 검사할 수 있다.

```bash
python3 -m sft_pipeline.experiments.planner_runtime_v2.build_dataset
python3 -m sft_pipeline.build.lib.validate_dataset \
  --in sft_pipeline/experiments/planner_runtime_v2/data/planner_runtime_v2_gold_300.jsonl
```

## 3. 분리된 본 학습

```bash
EXPERIMENT_ROOT=outputs/planner-runtime-v2-run1 \
EPOCHS=1.0 \
bash sft_pipeline/experiments/planner_runtime_v2/train_runpod.sh \
  2>&1 | tee /workspace/planner-runtime-v2-run1.log
```

스크립트가 다음을 순서대로 수행한다.

1. CUDA와 정확히 300건인지 확인
2. 데이터 스키마·날짜·중복·언어 검사
3. 결정론적 90:10 train/valid 분리
4. Qwen2.5-7B QLoRA 1 epoch 학습
5. 미학습 20개 요청에 운영과 같은 JSON 1회 재시도·code allocator를 적용해 평가
6. 승격 기준 미달이면 exit code 1 반환

재실행할 때 같은 디렉터리를 덮어쓰지 않는다.

```bash
EXPERIMENT_ROOT=outputs/planner-runtime-v2-run2 \
EPOCHS=1.0 \
bash sft_pipeline/experiments/planner_runtime_v2/train_runpod.sh
```

## 4. 합격 기준

`outputs/planner-runtime-v2-run1/eval_report.json`에서 확인한다.

- JSON/runtime 스키마 파싱률 85% 이상
- 날짜·30일·15개 제한 정합성 80% 이상
- 마감일 준수율 75% 이상
- 비시험 목표의 시험 내용 혼입 0건
- 불필요한 영어 단어 혼입 0건

학습 성공 메시지만으로 배포하지 않는다. 위 자동 평가와 실제 챗봇 노트북 테스트를
모두 통과해야 한다.

학습은 끝났지만 평가 단계만 실패했다면 재학습하지 말고 기존 adapter로 평가만 다시 실행한다.

```bash
python3 -m sft_pipeline.experiments.planner_runtime_v2.evaluate \
  --adapter outputs/planner-runtime-v2-run1/adapter \
  --out outputs/planner-runtime-v2-run1/eval_report.json
```

## 5. 신규 HF 저장소에 업로드

기존 저장소를 덮어쓰지 않는다.

```bash
python3 -m pip install -U huggingface_hub
hf auth login
```

```bash
python3 - <<'PY'
from huggingface_hub import HfApi

repo_id = "bigmooon/qwen2.5-7b-mongle-planner-runtime-v2"
folder = "outputs/planner-runtime-v2-run1/adapter"
api = HfApi()
api.create_repo(repo_id, repo_type="model", private=True, exist_ok=True)
api.upload_folder(repo_id=repo_id, repo_type="model", folder_path=folder)
print(repo_id)
PY
```

## 6. 기존 서비스와 나란히 시험

RunPod에서 기존 플래너 템플릿을 수정하지 말고 복제해 테스트 엔드포인트를 만든다.

테스트 템플릿 환경변수:

```text
LORA_PLANNER_REPO=bigmooon/qwen2.5-7b-mongle-planner-runtime-v2
HF_TOKEN=<PRIVATE_REPO_TOKEN>
```

테스트 엔드포인트 URL과 API 키를 `.env`의 테스트 설정에만 넣는다.

```text
RUNPOD_PLANNER_ENDPOINT_URL=<기존 운영 엔드포인트>
RUNPOD_PLANNER_V2_ENDPOINT_URL=<복제한 V2 테스트 엔드포인트>
RUNPOD_API_KEY=<RUNPOD_API_KEY>
```

이 폴더의 `planner_ab_test.ipynb`를 커널 재시작 후 전체 실행하면 같은 요청을 기존/V2에
각각 보내 결과를 나란히 확인할 수 있다. 기존 운영 엔드포인트의
`LORA_PLANNER_REPO`는 바꾸지 않는다.

비교할 핵심 요청:

```text
흑백요리사에서 우승하고 싶어
슈퍼스타K에 출연하고 싶어
8월 8일 철인 삼종 경기에 출전하고 싶어
이번 달에 운동이랑 공부를 챙기고 싶어
아까 만든 계획에서 평일 운동을 저녁으로 바꿔줘
```

신규 엔드포인트가 자동 평가와 대화 테스트를 모두 통과하면 운영 템플릿의
`LORA_PLANNER_REPO`를 신규 repo로 변경하고 워커를 재시작한다. 문제가 있으면 테스트
엔드포인트만 내리면 되며 기존 서비스에는 영향이 없다.
