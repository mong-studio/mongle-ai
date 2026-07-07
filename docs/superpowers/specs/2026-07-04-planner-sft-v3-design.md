# Planner SFT v3 — 파인튜닝 재시도 설계

날짜: 2026-07-04 · 브랜치: `feat/planner-sft-v3` · 상태: 설계 승인됨

## 1. 목표와 비목표

**목표: 파인튜닝 성공 자체의 증명.** planner LoRA가 "플랜 생성 단일 노드"에서
base+프롬프트 대비 측정 가능하게 우수함을 승격 게이트로 입증한다. 게이트를
수치로 통과하면 승격, 수치로 미달하면 기각 — **측정된 기각도 유효한 종착지**다
(지난 실패의 "게이트 미실행"과 구분되는 결과물).

**비목표:**
- 분류(judge)·꼬리질문(follow_up)·검증(critic)의 SFT — 현행 base+코드 유지.
- routine 경로 변경 — 코드 전개(`expand_routine`) 유지.
- 운영 배포 — 게이트 통과 전 `LORA_PLANNER_REPO` 불변.
- 베이스 모델 교체 — EXAONE-3.5-7.8B 유지(워커·배포·train_plain 경로 실증됨).

## 2. 지난 실패 원인 → 이번 설계의 대응

| 실패 원인 | v3 대응 |
|---|---|
| 시험 편향 데이터 → 도메인 붕괴 | 목표 분포를 먼저 설계(일상 40/루틴 20/시험 20/범용 20), teacher 증류로 커버 |
| 결정론 템플릿 타깃 → 암기(loss 0.079) | 코드가 못 만드는 "태스크 내용·순서·난이도 판단"만 타깃 가치로 선별 + loss 하한 경고 체크포인트 |
| train/serve skew (`todos/calendar_events` vs `days`) | 학습 전 서빙 계약 스냅샷 + sync 테스트 동결 |
| 평가 게이트 설계만 되고 미실행 | A/B 실행·출력 커밋을 승격의 필수 관문으로 |
| 플랜 정합성 위반을 critic이 미탐지(기계적 분할·목표 무관 태스크 통과) | 3단 게이트 루브릭(구조 불변식 S2~S5 + 의미 M1~M4 채점)을 데이터 필터와 승격 게이트 양쪽에 동일 적용 |
| 모델 직무 미정의 | 플랜 생성 단일 노드로 고정 |

## 3. 아키텍처: V2 뼈대 재활용

`sft_pipeline/experiments/planner_runtime_v2/`의 격리 원칙(별도 출력 경로·별도
HF repo·승격 게이트·A/B 노트북)을 `sft_pipeline/experiments/planner_sft_v3/`로
복제한다. 교체되는 것은 **데이터 생성기뿐**이다.

```text
sft_pipeline/experiments/planner_sft_v3/
├── README.md                 # 실행·평가·승격·롤백 절차
├── contract.py               # 서빙 계약 스냅샷(프롬프트+guided JSON 스키마+파서)
├── goal_corpus.py            # 목표 분포 정의 + 시드 목표 목록
├── distill_dataset.py        # teacher 호출 → 검증 필터 → JSONL
├── data/planner_sft_v3_gold.jsonl
├── train_runpod.sh           # train_plain.py 격리 진입점 (V2 미러)
├── evaluate.py               # holdout 승격 평가 (V2 확장)
├── ab_test.ipynb             # base vs LoRA 나란히 비교 (V2 미러)
└── tests/                    # 계약 sync·데이터 재현성·필터 검사
```

재사용(읽기 전용): `sft_pipeline/train/train_plain.py`(EXAONE 함정 5종 수정 포함),
`sft_pipeline/build/lib/validate_dataset`, coherence 검증기.

## 4. 1단계 — 서빙 계약 동결 (다른 무엇보다 먼저)

`contract_snapshot.py`가 런타임 `generate_plan`의 system 프롬프트와 guided JSON
스키마(`summary_text`/`days[]`)를 **미러 상수**로 보유하고, sync 테스트가 런타임
원본과 문자 단위 일치를 검사한다(기존 `plan_schemas.py` 미러+sync 패턴).
학습 도중 런타임 계약이 바뀌면 테스트가 깨져 즉시 드러난다. 데이터·평가·A/B는
전부 이 스냅샷만 사용한다.

## 5. 2단계 — 데이터: Teacher 증류 + 검증 필터

- **목표 코퍼스**: `goal_corpus.py`에 분포 명시 — 일상 40% / 루틴 20% / 시험 20% /
  범용 프로젝트 20%. "흑백요리사에서 우승하고 싶어" 류 미지 목표를 범용에 필수
  포함(V2 README의 비교 요청 5종은 전부 holdout으로 예약, 학습 금지).
- **생성**: GPT-4o가 계약 스냅샷 프롬프트로 플랜 생성. 입력은 (goal, parsed_goal,
  today)의 결정론 조합 — today는 고정 시드로 다양화.
- **검증 필터 = 3단 게이트(`evaluating-plan-coherence` 스킬 루브릭 준수)**:
  - **Gate 1 구문**: 계약 스키마 파싱 실패 → DROP.
  - **Gate 2 구조(항목별 PASS/FAIL, 1개라도 FAIL → DROP)**: S2 시간 논리(기간 내·
    30일·15개·마감일 준수), S3 사용자 명시 제약과 충돌 없음, S4 참조 무결성(입력에
    없는 자료·시험 내용 환각 금지 — 기존 시험혼입 스캔 포함, summary_text의 참조·
    수치도 검사), S5 분량 보존(입력이 요구한 총량과 플랜 항목 합계 일치), 동일
    태스크 무근거 중복 배치 금지. 한국어 검사(`is_korean_reply` 재사용)도 하드 FAIL.
  - **Gate 3 의미(LLM judge 채점, 차원별 1~5점)**: M1 분배 합리성("1일차, 2일차…"
    기계적 균등 분할 감점), M2 시간 현실성(항목당 부하·버퍼), M3 순서 논리(선행→
    후행 의존), M4 완결성(플랜대로 하면 목표 달성). 평균 ≥4.0 ACCEPT /
    3.0~3.9 FIX(teacher 재생성 1회 후 재평가) / <3.0 DROP.
  - 위반 샘플의 침묵 자동 교정 금지(FIX 분류 후 재검증만 허용). **드롭 사유 분포를
    리포트로 남기고 teacher 프롬프트 개선의 피드백 루프로 사용한다.**
- **규모**: 채택 기준 800~1,000건. holdout 30건은 분포 미러로 먼저 떼어 학습에서 제외.
- **원칙**: 날짜 분배처럼 코드가 계산할 수 있는 것은 학습 가치로 치지 않는다.
  타깃의 가치는 목표별 태스크 내용·순서·난이도 판단에 있다.

## 6. 3단계 — 학습

- `train_plain.py` QLoRA, EXAONE-3.5-7.8B, RunPod 24GB(3090/4090), epoch 1~2.
- 운영 수칙은 V2/파인튜닝 노트북의 검증된 것 유지: tmux 분리 실행, 어댑터 즉시
  S3 백업, `eval_strategy="no"`+저장 우선, HF offline 재실행.
- **암기 경고 체크포인트**: train_loss < 0.3이면 정지하고 데이터 다양성 재점검
  (지난 0.079 = 템플릿 암기의 재발 방지).
- 산출: `outputs/planner-sft-v3-run{N}/adapter`, HF repo
  `bigmooon/exaone-planner-sft-v3`(신규, 기존 repo 불변).

## 7. 4단계 — 평가 게이트 (실행이 관문)

`evaluate.py`가 holdout 30건에 운영과 동일한 JSON 재시도 1회를 적용하고,
**데이터 필터와 같은 3단 게이트 루브릭**으로 측정한다(필터↔게이트 기준 통일 —
학습 데이터가 통과한 기준으로 모델 출력도 심사):

- Gate 1 구문: JSON/계약 스키마 파싱률 ≥ 85%
- Gate 2 구조: 불변식(S2 시간 논리·S3 제약 충돌·S4 참조 무결성·S5 분량 보존)
  위반률 ≤ 20%, 그중 시험 내용 혼입·근거 없는 영어 혼입은 0건(하드)
- 마감일 준수율 ≥ 75%
- Gate 3 의미: M1~M4 평균 ≥ 3.5 (LLM judge, 필터와 동일 채점 프롬프트)

**A/B 필수 관문**: `ab_test.ipynb`를 실제 실행해 base+프롬프트 vs LoRA를 같은
holdout으로 비교하고 **출력이 박힌 노트북을 커밋**한다. 비교 지표는 위 게이트
수치 전부 — 특히 **의미 평균(M1~M4)에서 LoRA ≥ base**가 승격 조건이다(정합성
개선의 직접 증거). 우위가 없으면 수치와 함께 기각 판정을 기록한다. 미달이면
exit 1 — 학습 성공 메시지만으로 승격하지 않는다.

## 8. 격리·롤백

- 새 브랜치 `feat/planner-sft-v3`, 신규 HF repo, 출력 `outputs/planner-sft-v3-*`.
- 운영 어댑터·기존 데이터·V2 실험 디렉토리 무수정.
- 승격 시에만 RunPod 템플릿 복제 → 테스트 엔드포인트 검증 → `LORA_PLANNER_REPO`
  변경(V2 README §6 절차 그대로). 문제 시 env 롤백만으로 복구.
- ⚠️ `sft_pipeline/`은 `.gitignore` 대상 — 신규 파일은 `git add -f` 필수.

## 9. 성공 기준

1. 게이트 5개 수치 전부 통과 **그리고** A/B에서 base 대비 우위 → 승격 자격.
2. 또는 수치 기반 기각 + 원인 기록(eval_report.json + A/B 노트북) → 검증 완결.

둘 중 하나에 도달하면 이 실험은 성공이다. 도달하지 못하는 유일한 실패는
"게이트를 실행하지 않는 것"이다.

## 10. 리스크

- **teacher 품질 상한**: LoRA는 GPT-4o를 넘을 수 없다 — 목표가 "증명"이므로 수용.
- **7B 한국어 충실도**: 희귀어 손상은 SFT로 안 고쳐질 수 있음 — 기존 사후
  repair가 런타임에 있으므로 게이트에서 제목 손상은 blocking 아닌 기록 항목.
- **API 비용**: 증류 ~1,300회(기각분 포함) + 평가 호출, 수만 원 수준 예상.
  distill은 중간 저장으로 재개 가능하게 한다.
