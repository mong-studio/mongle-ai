# 정보처리기사 SFT Dry-Run 보고서

- **일자:** 2026-06-09
- **대상:** 정보처리기사 SFT 내부 학습 후보
- **목적:** 데이터 포맷, validator, Qwen2.5-7B LoRA 학습 진입, adapter 저장 여부 확인
- **실행 환경:** RunPod GPU 인스턴스

## 1. 데이터셋 요약

| 파일 | 건수 | 설명 |
| --- | ---: | --- |
| `exam_information_processing_engineer_training_sft.jsonl` | 145 | 정처기 runtime plan + follow_up 합본 |
| 초기 단독 train split | 130 | 이후 distractor mixed split으로 대체되어 파일 삭제 |
| 초기 단독 valid split | 15 | 이후 distractor mixed split으로 대체되어 파일 삭제 |

분포:

| Split | exam-crawl plan | exam-follow-up-synth | 합계 |
| --- | ---: | ---: | ---: |
| train | 40 | 90 | 130 |
| valid | 5 | 10 | 15 |

## 2. 사전 검증

공통 validator 결과:

```text
초기 단독 train split: [validate] ok=130 errors=0
초기 단독 valid split: [validate] ok=15 errors=0
```

로컬 학습 환경 점검 결과:

```text
torch 2.11.0
cuda False
mps False
datasets import failed: ModuleNotFoundError
peft import failed: ModuleNotFoundError
unsloth import failed: ModuleNotFoundError
```

따라서 로컬에서는 데이터 dry-run까지만 수행하고, 실제 LoRA 학습은 RunPod에서 수행했다.

## 3. RunPod 실행

사용 스크립트:

```bash
bash sft_pipeline/train/runpod_ipe_dryrun.sh
```

기본 설정:

| 항목 | 값 |
| --- | --- |
| model | `Qwen/Qwen2.5-7B-Instruct` |
| epochs | `0.10` |
| max_seq_len | `2048` |
| batch | `1` |
| grad_accum | `4` |
| output | `outputs/ipe-qwen7b-dryrun-lora` |

## 4. RunPod 결과

사용자 확인 로그:

```text
[train] LoRA 어댑터 저장: outputs/ipe-qwen7b-dryrun-lora
[train] 학습 후 점검: validation loss 확인(0.2 미만이면 과적합 경고), EOS 스모크 테스트, 생성물을 plan_schemas.parse_plan 으로 파싱해 성공률 측정(sft-coherence phase 6).
[runpod] dry-run complete: outputs/ipe-qwen7b-dryrun-lora
```

생성된 adapter 파일:

```text
outputs/ipe-qwen7b-dryrun-lora
├── README.md
├── adapter_config.json
├── adapter_model.safetensors        # 155M
├── chat_template.jinja
├── checkpoints/
├── tokenizer.json
└── tokenizer_config.json
```

## 5. Postcheck 결과

개선된 `runpod_ipe_dryrun.sh` 재실행 후 `postcheck_report.json`을 회수했다.

파일:

```text
outputs/ipe-qwen7b-dryrun-lora/postcheck_report.json
```

결과:

| 항목 | 값 | 판정 |
| --- | ---: | --- |
| n_samples | 5 | dry-run 소량 점검 |
| eos_rate | 1.0 | 정상 |
| parse_success_rate | 0.4 | 개선 필요 |
| eval_loss | null | trainer_state 기반 eval_loss 미확보 |
| overfit_warning | null | 경고 없음 |

파싱 실패는 5건 중 3건이며, 모두 `calendar_events.0.due_date`가 유효한 ISO 날짜로 파싱되지 않은 문제였다. 즉 EOS 종료와 adapter 저장은 정상이나, 짧은 dry-run 모델의 구조화 플랜 날짜 출력 정합성은 아직 부족하다.

대표 실패:

```text
[파싱] 플랜 출력 파싱 실패: calendar_events.0.due_date
Input should be a valid date or datetime
```

회수된 산출물:

```text
ipe_dryrun_adapter_with_report.tgz                 # 142M
outputs/ipe-qwen7b-dryrun-lora/adapter_model.safetensors  # 154M
outputs/ipe-qwen7b-dryrun-lora/postcheck_report.json       # 1.1K
```

## 6. 판정

이번 dry-run은 **학습 파이프라인 검증 관점에서는 성공**, **모델 출력 품질 관점에서는 개선 필요**로 판정한다.

- train/valid split 모두 validator 통과
- RunPod에서 Qwen2.5-7B LoRA 학습 진입 성공
- `SFTTrainer` 경로가 중단 없이 실행됨
- LoRA adapter 저장 성공
- postcheck 리포트 생성 성공
- EOS 종료율 100%
- 구조화 플랜 파싱 성공률 40%로 낮음

## 7. 다음 작업

1. 완료: `postcheck.py`가 실패 출력 전문, 긴 preview, raw/clean 샘플 출력을 저장하도록 확장했다.
2. 완료: gold distractor 9건을 정처기 145건과 섞은 mixed set을 구성했다.
3. 날짜 형식 오류를 줄이기 위해 본 학습에서는 daily 및 더 많은 runtime plan 데이터를 추가로 섞는다.
4. 정처기+distractor mixed train set으로 다시 RunPod dry-run 한다.
5. 필요하면 학습 데이터를 보강해 `calendar_events.due_date`가 반드시 `YYYY-MM-DD`임을 더 강하게 반복한다.

## 8. Distractor Mixed Set

정처기 단독 145건에 gold distractor 9건을 추가해 총 154건 mixed set을 만들었다.

| 파일 | 건수 | 설명 |
| --- | ---: | --- |
| `distractor_gold_sft.jsonl` | 9 | out_of_scope 6, chit_chat 3 |
| `ipe_distractor_mix_sft.jsonl` | 154 | 정처기 145 + distractor 9 |
| `ipe_distractor_dryrun_train.jsonl` | 138 | mixed train split |
| `ipe_distractor_dryrun_valid.jsonl` | 16 | mixed valid split |

분포:

| Split | exam-crawl plan | exam-follow-up-synth | distractor | 합계 |
| --- | ---: | ---: | ---: | ---: |
| train | 40 | 90 | 8 | 138 |
| valid | 5 | 10 | 1 | 16 |

assistant 출력 유형:

| 파일 | runtime plan | follow_up | out_of_scope | chit_chat |
| --- | ---: | ---: | ---: | ---: |
| `ipe_distractor_mix_sft.jsonl` | 45 | 100 | 6 | 3 |

검증:

```text
python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_distractor_mix_sft.jsonl
[validate] ok=154 errors=0

python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_distractor_dryrun_train.jsonl
[validate] ok=138 errors=0

python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_distractor_dryrun_valid.jsonl
[validate] ok=16 errors=0
```

`runpod_ipe_dryrun.sh`의 기본 train/valid 입력도 위 mixed split으로 갱신했다.

## 9. Distractor Mixed RunPod 결과

mixed split으로 RunPod dry-run을 재실행했고, `postcheck_report.json`을 회수했다.

원본 리포트:

```text
sft_pipeline/reports/ipe_distractor_postcheck_report_2026-06-10.json
```

결과:

| 항목 | 이전 정처기 단독 | distractor mixed | 판정 |
| --- | ---: | ---: | --- |
| n_samples | 5 | 5 | dry-run 소량 점검 |
| eos_rate | 1.0 | 1.0 | 정상 유지 |
| parse_success_rate | 0.4 | 0.6 | 개선됐지만 부족 |
| eval_loss | null | null | trainer_state 기반 eval_loss 미확보 |
| overfit_warning | null | null | 경고 없음 |

mixed dry-run은 파싱 성공률을 40%에서 60%로 올렸지만, 아직 구조화 출력 품질은 충분하지 않다.

실패 유형:

| 유형 | 예시 | 의미 |
| --- | --- | --- |
| 날짜 오타 | `22026-07-08`, `2206-07-09` | `due_date`가 ISO 날짜로 파싱되지 않음 |
| 제목 길이 초과 | `소프트웨어 개발 보안 구축 관련 문제 품` | `title <= 20` 제약 위반 |
| 중국어 혼입 | `编程`, `模拟考试`, `全面复习` | 한국어 서비스 출력 품질 위반 |
| C5 분기 위반 가능성 | 미래 날짜가 `todos`에 등장 | 오늘 할 일과 미래 일정 분기 약화 |

이번 실행의 의미:

- 학습 파이프라인과 postcheck 저장은 정상이다.
- distractor 혼합은 경계 행동에는 필요하지만, 날짜·언어·title 길이 정합성 문제를 충분히 해결하지 못한다.
- 다음 개선은 distractor 추가가 아니라 runtime plan 데이터 증량, 언어 게이트, 날짜/길이 제약을 반영한 postcheck 강화 쪽이 우선이다.

## 10. Runtime Hardening Set

mixed dry-run 실패 유형을 직접 겨냥해 runtime hardening 80건을 추가했다.

보강 목표:

| 목표 | 반영 방식 |
| --- | --- |
| ISO 날짜 | 모든 `due_date`를 `YYYY-MM-DD`로 고정 |
| 짧은 제목 | 모든 `title`을 20자 이하 명사구로 구성 |
| 한국어 태그 | `tags`에 한국어 태그만 사용 |
| C5 분기 | 기준일 당일은 `todos`, 미래 날짜는 `calendar_events`로 분리 |

데이터 구성:

| 파일 | 건수 | 설명 |
| --- | ---: | --- |
| `exam_information_processing_engineer_hardening_sft.jsonl` | 80 | 구조화 출력 보강 synthetic |
| `ipe_hardened_mix_sft.jsonl` | 234 | 기존 mixed 154 + hardening 80 |
| `ipe_hardened_dryrun_train.jsonl` | 210 | hardened train split |
| `ipe_hardened_dryrun_valid.jsonl` | 24 | hardened valid split |

분포:

| Split | exam-crawl plan | exam-follow-up-synth | exam-synth hardening | distractor | 합계 |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 40 | 90 | 72 | 8 | 210 |
| valid | 5 | 10 | 8 | 1 | 24 |

검증:

```text
python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/exam_information_processing_engineer_hardening_sft.jsonl
[validate] ok=80 errors=0

python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_hardened_mix_sft.jsonl
[validate] ok=234 errors=0

python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_hardened_dryrun_train.jsonl
[validate] ok=210 errors=0

python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_hardened_dryrun_valid.jsonl
[validate] ok=24 errors=0
```

`runpod_ipe_dryrun.sh`의 기본 train/valid 입력은 이제 hardened split이다.

## 11. Seed Prompt Alignment

초기 gold seed인 `sft_pipeline/data/seeds/exam.jsonl`의 system prompt 철학을 최종
정처기 dry-run 데이터셋에도 반영했다.

반영한 항목:

| 항목 | 처리 |
| --- | --- |
| 라우팅 규칙 | out_of_scope / chit_chat / follow_up / plan 유지 |
| 필수 수집 슬롯 | 여행·시험·과제·루틴 슬롯 규칙 유지 |
| follow_up 정책 | 정보 부족 시 질문 1개, 최대 2회 후 가정 plan 원칙 유지 |
| plan 스키마 | 기존 `phases` 대신 런타임 `summary_text/todos/calendar_events`로 조정 |
| 품질 규칙 | 마감 역산, 하루 2~4 task, 구체적 제목, ISO 날짜, C5 분기 강화 |

그대로 복사하지 않은 이유는 현재 SFT 목표가 `agents/todo_creation` 런타임 출력과
맞는 구조화 플랜 생성이기 때문이다. 따라서 `exam.jsonl`의 라우팅/행동 정책은
살리고, plan 출력만 런타임 미러 스키마로 바꿨다.

## 12. Phase Preservation

초기 정처기 구조화 데이터는 시험 준비 과정을 `phases`로 명시했다. 최종 학습용
런타임 데이터에서는 `phases` 필드를 직접 출력하지 않지만, phase 정보는 다음처럼
보존했다.

| 단계 | 보존 방식 |
| --- | --- |
| 검수용 합본 | `exam_information_processing_engineer_all_sft.jsonl` 45건 모두 `phases` 필드 유지 |
| 런타임 변환 | 각 phase의 task를 `todos` 또는 `calendar_events`로 펼침 |
| phase 이름 | 변환된 task의 `tags`에 phase명을 추가 |
| 변환 이력 | `meta.converted_from_schema = "exam-phases-v1"` 기록 |
| C5 분기 | 기준일 당일 task는 `todos`, 미래 날짜 task는 `calendar_events`로 이동 |

집계:

| 파일 | 건수 | `phases` 직접 출력 | phase 보존 형태 |
| --- | ---: | ---: | --- |
| `exam_information_processing_engineer_all_sft.jsonl` | 45 | 45 | 원본 phases |
| `exam_information_processing_engineer_runtime_sft.jsonl` | 45 | 0 | tags + 일정 순서 |
| `ipe_hardened_dryrun_train.jsonl` | 210 | 0 | train 내 exam-crawl 40건 |
| `ipe_hardened_dryrun_valid.jsonl` | 24 | 0 | valid 내 exam-crawl 5건 |

대표 phase 태그:

```text
기출·오답 누적, 실전 마무리, 개념 1회독, 기출 집중 회독,
시험 직전 점검, 1주차 개념·기출, 2주차 약점 보완, D-1 최종 정리
```

따라서 phase는 삭제된 것이 아니라, 런타임 출력 스키마에 맞춰
`todos/calendar_events`의 날짜 배치와 `tags`로 투영된 상태다.

## 13. Hardened RunPod 결과

hardened split으로 RunPod dry-run을 재실행했고, 결과 아카이브
`ipe_hardened_dryrun_outputs.tgz`를 회수했다.

원본 리포트:

```text
sft_pipeline/reports/ipe_hardened_postcheck_report_2026-06-10.json
```

주의: 로컬에 있던 `outputs/postcheck_report.json`은 2026-06-08 파일이라 이번
RunPod 결과가 아니다. 이번 결과 판정은 tar 내부
`outputs/ipe-qwen7b-dryrun-lora/postcheck_report.json`을 기준으로 한다.

결과:

| 항목 | distractor mixed | hardened split | 판정 |
| --- | ---: | ---: | --- |
| n_samples | 5 | 5 | dry-run 소량 점검 |
| eos_rate | 1.0 | 1.0 | 정상 유지 |
| parse_success_rate | 0.6 | 0.4 | 악화 |
| eval_loss | null | null | trainer_state 기반 eval_loss 미확보 |
| overfit_warning | null | null | 경고 없음 |

실패 유형:

| 유형 | 관찰 |
| --- | --- |
| 라우팅 충돌 | plan이 필요한 샘플에서 `follow_up` 형태를 생성해 plan parser 실패 |
| 중복 JSON 출력 | 올바른 JSON 뒤에 ```json 코드블록을 한 번 더 출력해 `Extra data` 발생 |
| 날짜 오타 재발 | `2206-07-08` 같은 비정상 due_date가 다시 등장 |
| 영문 태그 | `programming`, `sql`, `security`, `exam` 태그가 등장 |
| C5 분기 약화 | 미래 날짜 task가 `todos`에 들어가는 출력이 관찰됨 |

해석:

- 데이터 검증은 통과했지만, 짧은 dry-run 학습만으로 출력 구조가 안정화되지는 않았다.
- hardening 샘플 80건은 방향은 맞지만, plan-only postcheck에서 follow_up 샘플이 섞인
  valid set을 그대로 평가하면 성공률이 낮게 측정될 수 있다.
- 다음 단계는 데이터 추가보다 먼저 postcheck를 개선해 `meta.kind`/assistant kind별로
  평가를 분리하고, plan 출력에 대해서만 `parse_plan` 및 정합성 검사를 적용하는 것이다.

## 14. Postcheck 개선 방향

hardened 결과를 근거로 `postcheck.py`를 kind별 평가로 확장했다. 이제 단순히 모든
생성물을 plan으로 파싱하지 않고, 정답 assistant의 종류를 기준으로 route와 schema를
분리해 본다.

추가한 평가 항목:

| 항목 | 의미 |
| --- | --- |
| `kind_eval.route_success_rate` | 정답 kind(plan/follow_up/out_of_scope/chit_chat)를 맞췄는지 |
| `kind_eval.by_expected_kind` | expected kind별 parse/route/consistency 성공률 |
| plan `consistency_success_rate` | `check_plan_consistency` 기반 날짜 범위·C5 분기·분량 검사 |
| plan tag 검사 | `programming`, `security`, `exam` 같은 영문 태그 감지 |

다음 RunPod에서는 새 학습 없이도 같은 어댑터에 대해 개선된 postcheck만 다시 실행해
실패를 더 정확히 분해할 수 있다.

## 15. Postcheck v2 결과

같은 hardened dry-run adapter에 대해 개선된 postcheck만 재실행했다.

원본 리포트:

```text
sft_pipeline/reports/ipe_hardened_postcheck_report_v2_2026-06-10.json
```

전체 결과:

| 항목 | 값 | 해석 |
| --- | ---: | --- |
| n_samples | 20 | valid 샘플 20건 평가 |
| eos_rate | 1.0 | 생성 종료 정상 |
| kind_eval.route_success_rate | 0.65 | plan/follow_up 라우팅이 아직 불안정 |
| kind_eval.parse_success_rate | 0.70 | JSON 형태 자체는 일부 개선 |
| legacy plan parse_success_rate | 0.50 | plan 기준으로 보면 절반 수준 |

kind별 결과:

| expected kind | n | route 성공률 | parse 성공률 | plan 정합성 성공률 | 실제 출력 분포 |
| --- | ---: | ---: | ---: | ---: | --- |
| follow_up | 8 | 0.75 | 1.00 | - | follow_up 6, plan 2 |
| plan | 12 | 0.58 | 0.50 | 0.25 | plan 7, follow_up 4, invalid_json 1 |

주요 실패 유형:

| 유형 | 건수 | 의미 |
| --- | ---: | --- |
| route mismatch | 5 | plan/follow_up 판단 불안정 |
| C5 분기 오류 | 2 | 미래 날짜가 `todos`에 들어감 |
| 날짜 오류 | 2 | horizon 초과 또는 `22026-...` 날짜 오타 |
| 영문 태그 | 2 | `programming`, `security`, `exam` 등 |
| 중복 JSON/Extra data | 1 | JSON 뒤에 코드블록을 추가 출력 |

판정:

- 평가기는 이제 문제를 더 잘 분리한다.
- 모델은 EOS와 JSON 출력은 어느 정도 유지하지만, plan 라우팅과 plan 정합성이 부족하다.
- 특히 plan 샘플 12건 중 정합성 성공률이 25%라서 본 학습으로 바로 넘어가기에는 이르다.

다음 조치:

1. valid/test 샘플을 plan-only, follow_up-only로 나눠 라우팅과 구조화 성능을 따로 본다.
2. plan 데이터에는 “충분한 정보가 있으면 절대 follow_up 하지 말라”는 hardening을 추가한다.
3. follow_up 데이터에는 반드시 `question` 필드를 포함하도록 출력 예시를 보강한다.
4. plan hardening은 C5/날짜/한국어 태그 중심으로 더 늘리되, valid set에 같은 패턴이 과도하게 반복되지 않도록 분리한다.

## 16. Hardened v2 Dataset

postcheck v2 결과를 바탕으로 두 축을 추가 보강했다.

보강 목적:

| 축 | 목적 |
| --- | --- |
| plan route hardening | 충분한 정보가 있으면 `follow_up`하지 않고 plan을 출력 |
| follow_up schema hardening | `message`만 쓰지 않고 반드시 `question` 필드를 포함 |
| single JSON hardening | JSON 뒤에 코드블록/두 번째 JSON을 덧붙이지 않도록 반복 |
| plan consistency hardening | C5 분기, ISO 날짜, 한국어 태그를 재강화 |

추가 데이터:

| 파일 | 건수 | 구성 |
| --- | ---: | --- |
| `exam_information_processing_engineer_postcheck_hardening_sft.jsonl` | 136 | plan 96 + follow_up 40 |
| `ipe_hardened_v2_mix_sft.jsonl` | 370 | 기존 hardened 234 + postcheck hardening 136 |
| `ipe_hardened_v2_dryrun_train.jsonl` | 332 | 중복 제거 후 train |
| `ipe_hardened_v2_dryrun_valid.jsonl` | 38 | 중복 제거 후 valid |
| `ipe_hardened_v2_valid_plan_only.jsonl` | 23 | plan 평가 전용 valid |
| `ipe_hardened_v2_valid_followup_only.jsonl` | 14 | follow_up 평가 전용 valid |

분포:

| Split | plan | follow_up | out_of_scope | chit_chat | 합계 |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 198 | 126 | 5 | 3 | 332 |
| valid | 23 | 14 | 1 | 0 | 38 |

검증:

```text
python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_hardened_v2_dryrun_train.jsonl
[validate] ok=332 errors=0

python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_hardened_v2_dryrun_valid.jsonl
[validate] ok=38 errors=0

python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_hardened_v2_valid_plan_only.jsonl
[validate] ok=23 errors=0

python3 -m sft_pipeline.build.validate_dataset --in sft_pipeline/data/generated/ipe_hardened_v2_valid_followup_only.jsonl
[validate] ok=14 errors=0
```

`runpod_ipe_dryrun.sh`의 기본 입력은 v2 train/valid로 갱신했다. 다음 실행에서는
학습 dry-run 후 `postcheck_report.json`의 kind별 지표를 v1과 비교한다.
