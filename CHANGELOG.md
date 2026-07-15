# CHANGELOG

본 프로젝트의 주요 변경사항을 기록한다. 포맷은 [Keep a Changelog 1.1.0](https://keepachangelog.com/ko/1.1.0/) 을 따른다.

> **이 파일은 팀 공유용이다.** 내부 작업·결정 로그는 `docs/TODO.md` 를 사용한다.
>
> **갱신 규칙:** 파이프라인을 만들거나 변경할 때마다 항목을 추가한다. 완성 정의는 `docs/FEATURES.md` §4 참조.

## sft_pipeline 추가 (2026-06-04)

- 합법-우선 SFT 데이터셋 파이프라인 `sft_pipeline/` 신설.
- crawl(robots 강제 준수·실패 로그) → structure(정규화·검증) → build(템플릿/선택적 LLM) → validate 4단계 CLI.
- 오프라인 `--mock` 재현, 합성 샘플 12건, 전처리 보고서 템플릿, 초보자 README 포함.

## [Unreleased]

### Added
- **Planner Runtime V2 격리 학습 키트**: 기존 planner LoRA·구형 `kind/phases` 데이터를 유지한 채,
  현재 `summary_text/personalization_patch/days` 계약만 학습하는 결정론적 300건 데이터셋과
  생성기, RunPod 전용 학습 스크립트, 20개 holdout 승격 평가기를 추가했다. 신규 출력은
  `outputs/planner-runtime-v2-*`, 신규 HF repo, 복제한 RunPod 테스트 엔드포인트를 사용해
  운영 어댑터를 덮어쓰지 않는다. 관련 파일과 실행 절차는
  `sft_pipeline/experiments/planner_runtime_v2/`에 격리했다.
- **피드 풀 파이프라인 (RunPod `feed` 모드)**: 피드 이미지가 "정면 캐릭터 스프라이트 한 장"만
  생성되던 것을, Hadimee `mongle-bg-lora/feed_pipeline` 5단계(캐릭터 img2img 포즈 변환 → rembg
  누끼 → 배경 text2img → 합성+그림자+rim마스크 → inpaint 경계 블렌딩)로 확장. 5단계는 GPU
  inpaint 가 필요해 RunPod 워커 안 `feed_mode.FeedMode` 에서 in-process 수행(SDXL 1벌,
  char+bg+lcm LoRA, `from_pipe` 공유)하고, 에이전트는 워커를 1회 호출한다.
  - 에이전트 그래프 단순화: `gen_feed_prompt(LLM action/scene 분해) → feed_image → s3_upload →
    gen_caption_prompt → llm_caption → builder`. 입력/출력 검증을 LangGraph 노드에서 Pydantic
    스키마로 이전(`validate`/`validate_caption` 노드 제거; caption ≤140·한글은 `GeneratedFeed`).
  - 스키마 필드 개명 `appearance_keywords→visual`, `quest_text→quest` (구 키 `AliasChoices` 호환 →
    mongle-server payload 무중단 전환). 워커 `adapter="feed"` 추가 + 모드 lazy-load + `scene_prompt`
    계약. 워커/RunPod LoRA env 는 불변(이미 char+bg 둘 다 설정).
- **캐릭터 appearance 영어 번역 노드 (이미지 충실도 수정)**: SDXL 텍스트 인코더(CLIP)가
  영어 전용이라 한국어 `appearance`(외형)가 이미지에 반영되지 않던 문제. 라이브 검증으로
  확인(한국어 "갈색 곰"→초록 blob, 동일 의미 **영어**→정확한 여우). 페르소나 그래프에
  `translate_appearance` 노드 추가(llm_persona→translate→sync): **Qwen base(`adapter="base"`,
  no-LoRA)**로 한국어 외형을 영어 visual 태그로 변환해 `llm_result.appearance` 를 갱신한다.
  번역 실패 시 한국어 원본 유지(비치명적). `TranslatorPort`+`RunPodTranslator`(planner 엔드포인트
  base)/`QwenTranslator`(로컬). DB `visual`·이미지 prompt 가 영어가 되며(표시용 페르소나는
  personality/speech_style/background 한국어 유지) 이미지 워커는 불변.
- **단일 `/v1/todo/generate` out_of_scope 처리**: "배고프다"처럼 일정/TODO로 나눌 수 없는 입력을
  억지 todo로 만들지 않고 `OutOfScopeResult`(`kind: "out_of_scope"`)로 안내한다. `split_tasks`가
  `intent`("plan"|"out_of_scope")를 함께 반환하도록 확장(`SplitResult`), 단일 그래프에 조건 분기 추가,
  응답모델을 `Envelope[SingleTurnResult]`로. LLM 호출 추가 없음. 설계·계획:
  `docs/superpowers/specs|plans/2026-06-13-generate-out-of-scope*`.

### Changed
- **RunPod 워커 CI/Docker 빌드 최적화**: `deploy-workers.yml` 에 변경 경로 감지 job과 concurrency를
  추가해 `llm`/`image_gen` 중 변경된 워커만 빌드한다. Docker BuildKit pip cache와 HF secret
  mount를 적용했고, `image_gen` 은 ML 의존성 설치 → SDXL/ControlNet/LCM bake → app 의존성 설치
  순서로 분리했다. 이미지 워커의 공용 모델 ID/revision은 `model_refs.py`로 통합해 bake와 런타임
  로더가 같은 revision을 사용한다.
- **텍스트 전용 캐릭터 이미지를 외형(appearance) 기반 text2img 로 전환**: 사진 없이 생성할 때
  기존엔 고정 회색 원 실루엣을 ControlNet img2img(매번 거의 동일한 blob)로 돌렸는데,
  LLM 이 생성한 `appearance` 묘사를 prompt 로 SDXL text2img(`character_mode.py`, 모델 카드 표준
  30 step·guidance 7.5·LoRA 0.9) 하여 페르소나별 고유 이미지를 만든다. `from_pipe` 로 SDXL/unet
  공유(VRAM 재사용). 오케스트레이터 `runpod_image` 가 payload 에 `prompt=appearance`(폴백 persona)
  동봉. 사진 있는 표준 img2img 경로는 불변.
  - 참고: v0.1.14 에서 모델 카드 LCM fast path(8 step·g1.5)를 시도했으나 **라이브 검증 결과
    저-guidance 로 외형 프롬프트 충실도가 무너지고(요청과 다른 색·종) 속도 이득도 미미(웜 63s)** →
    v0.1.15 에서 표준 30-step 으로 되돌림(외형 충실도 우선).
  **사진 있는 img2img 경로(표준 30-step)는 불변.** ⚠️ GPU 워커 재배포 필요(로컬 GPU 미검증).

### Fixed
- **TODO planner LoRA 출력 스키마 호환 복구**: RunPod/HuggingFace planner LoRA가
  `summary_text/todos/calendar_events` 런타임 응답 형태로 학습된 반면, 서빙 어댑터는
  `summary_text/days`만 성공으로 인정해 `missing days → 재시도 → deterministic fallback`으로
  떨어질 수 있던 문제를 수정했다. `generate_plan`의 guided JSON과 파서가 두 스키마를 모두
  허용하고, LoRA가 낸 `todos/calendar_events`를 내부 `PlanDay`로 정규화한다. 프롬프트도 두
  스키마를 명시해 정처기·토익·컴활·일상 등 SFT 데이터의 출력 습관을 런타임에서 살릴 수 있게 했다.
  또한 title 문자 집합 regex를 guided decoding에서 제거해, CJK regex 제약 때문에 학습 데이터에
  없는 `D-20 5000 4000`류 숫자 제목으로 무너지는 경로를 끊었다.
- **RunPod planner EXAONE 배포 확인성 개선**: planner가 EXAONE 기반으로 전환된 상태에서
  Qwen 시절 기본 LoRA repo가 다시 주입되지 않도록 최초 엔드포인트 생성 스크립트가
  `LORA_PLANNER_REPO`를 필수 환경변수로 요구한다. LLM 워커 부팅 로그에는 실제
  `LLM_BASE_MODEL`, revision, 등록된 LoRA repo, stop token id를 출력해 EXAONE base와
  planner LoRA 조합이 맞는지 운영 로그에서 바로 확인할 수 있게 했다.
- **TODO 플래너 정처기 실기 fallback 반복 완화**: `goal_tag`(6자 UI/DB 태그)만으로
  도메인 위키를 찾던 결합을 끊고, `plan_kind`/`goal_text`/`slots.exam_part`를 함께 보는
  공용 domain knowledge resolver를 추가했다. `goal_tag=정보처리기사`처럼 일반 태그여도
  `exam_part=실기`면 `정처기실기.md`가 생성 프롬프트와 안전 플랜 양쪽에 적용된다. LLM 출력이
  BTC 같은 목표 외 코드형 제목이나 필기/실기 불일치로 차단되어도 `범위 정리 30분` 고정
  fallback 대신 위키의 추천 태스크(`SQL 응용 기출풀기`, `C언어 손코딩 연습` 등)로 복구한다.
- **반복 루틴 응답 속도·일정 중복 수정**: 명확한 주간 횟수·요일이 있는 입력은 범용 classifier
  호출을 생략하고 planner judge 한 번으로 구조화한다. judge가 활동별 `routine_items`를 만들고,
  코드 전개기는 이를 선택 요일 순서에 배치하므로 헬스·러닝·학습 등 어떤 반복 활동도 회차별
  실행 항목으로 분리할 수 있다. 매회 같은 행동이 자연스러운 루틴은 기존 단일 제목을 유지한다.
- **플래너 범위 밖 응답·긴 JSON 안정화**: 일반 대화 응답이 맛집 검색·예약·주문처럼 지원하지
  않는 기능을 약속하면 안전한 계획 안내로 교체한다. TODO 모델 출력 한도를 2400 토큰으로
  늘리고, planner LoRA의 플랜 JSON이 재시도 후에도 깨지면 base 모델로 한 번 복구한다.
- **TODO 태그 길이 6자 제한**: 싱글턴·멀티턴 후보의 태그를 Pydantic 스키마에서 6자로
  제한하고, planner goal tag 프롬프트와 후처리도 같은 길이로 통일했다.
- **플래너 꼬리 질문 과잉 생성 수정**: 최종 플랜 전용 LoRA가 꼬리 질문까지 생성하던
  라우팅을 base 모델로 분리했다. 현재 계획 유형과 무관한 누락 슬롯은 제거하고, 한 번에 묻는
  조건을 최대 2개로 제한했다. 범용 project의 성공 기준은 선택 정보로 두어 목표를 다시
  표현하게 만들지 않으며, 질문 프롬프트는 설명·조언·예시 없이 100자 이하 질문만 반환한다.
- **범용 플랜 품질 심사 오판 완화**: base 심사자가 project 목표를 시험으로 재해석해 정상
  플랜까지 차단하던 문제를 수정했다. 심사 의견은 1회 재생성에 반영하되, 재시도 후 날짜·개수·
  상세 범위 같은 결정적 검증을 통과하면 주관적 의미 판정은 경고로만 남겨 응답을 보존한다.
  심사자의 JSON 출력이 깨져 파싱되지 않는 경우도 하드 검증 통과 플랜을 막지 않는다.
- **플래너의 미입력 날짜 생성 차단**: LLM이 사용자에게 받지 않은 경기일·시험일을 슬롯에
  만들어도 더 이상 일정 생성에 사용하지 않는다. 날짜는 전체 사용자 대화에서 코드 파서가
  실제 날짜 표현을 확인한 경우에만 `deadline/event_date/exam_date`로 인정한다.
- **멀티턴 플래너의 미지 목표 오분류·정처기 내용 혼입 수정**: 고정 유형에 없는 계획을
  `project`로 수용하고 base 모델이 근거·신뢰도와 함께 선분류한다. 꼬리질문은 최대 2회이며,
  날짜를 끝내 받지 못하면 목표일을 만들지 않고 첫 30일 실행안이라는 가정만 명시한다.
  정보처리기사처럼 검증된 시험 도메인만 planner LoRA로 생성하고 일반 목표는 base 모델로
  격리한다. 상세 일정은 최대 30일·15개로 코드 배치하며, 장기 목표의 30일 이후 구간은
  캘린더 항목을 만들지 않고 목표일까지의 간단한 흐름만 채팅 요약으로 안내한다. 비시험 계획의 시험 내용, 근거 없는 영어,
  빈 일정과 날짜 범위 위반은 LLM judge와 별개로 코드가 차단한다. 지원 시험 registry의
  별칭 누출, 동일 제목 과다 반복, 실행 기준 없이 목표명에 `훈련/준비/계획`만 붙인 제목도
  재생성 대상으로 처리하며, 재시도 후에도 깨지면 수집된 슬롯 기반의 최소 안전 플랜으로
  복구한다.
- **SFT LoRA 학습 `<EOS_TOKEN>` 반복 실패 해결**: `train_lora.py`가 `trl`을 `unsloth`보다 먼저 import해
  unsloth의 trl 몽키패치가 어긋나며 `eos_token`이 `<EOS_TOKEN>` placeholder로 새어 학습이 죽던 문제.
  **import 순서를 unsloth 우선으로 재배치**해 근본 해결(transformers 5.5.0 그대로, 다운그레이드 불필요).
  진단·오판 경로·재현 절차는 `sft_pipeline/train/TROUBLESHOOTING.md`. 근거: unsloth#2797 (maintainer:
  "always import unsloth first"). 검증: RTX 4090에서 Qwen2.5-7B QLoRA 2epoch 정상 수렴(loss 1.33→0.21).

### Changed
- **`/v1/todo/generate`·`/v1/todo/chat` 비동기 submit(202)+poll(GET) 전환**: planner LLM 이
  RunPod Pod 프록시의 100s 하드 타임아웃을 넘기므로(실측 ~90-105s), character 와 동일하게
  백그라운드 잡으로 분리한다. POST 는 즉시 `202` + `TodoJobRef(job_id)` 를 pending 봉투로 반환하고,
  `GET /v1/todo/generate/{job_id}`·`GET /v1/todo/chat/{job_id}` 로 폴링한다(pending/done/error/404).
  인메모리 잡 스토어 `TodoJobStore`(신규 `api/todo_creation/jobs.py`, DB/Redis 의존성 없음,
  `character_creation/jobs.py` 패턴 복제). `/v1/todo/commit` 은 동기 유지. 호출자(Django)는
  개별 요청을 100s 미만으로 보내며 전체는 폴링으로 기다려 프록시 타임아웃을 우회한다.
- **RunPod LLM 워커 멀티-LoRA 화 + planner/character 엔드포인트 분리**: LLM 워커를 멀티-LoRA
  가능 구조로(`enable_lora`, 설정된 어댑터만 등록) 만들고 요청 `input.adapter`("planner"|"character")로
  LoRA 를 고른다. 같은 이미지를 **planner 단독·character 단독 두 엔드포인트**로 배포(persona 가
  지배적·고변동이라 격리; planner 는 `workersMin=0` 으로 시작. 근거 `docs/adr/0005`). 오케스트레이터는
  `RUNPOD_PLANNER_ENDPOINT_URL`·`RUNPOD_CHARACTER_ENDPOINT_URL` 사용, payload 에 `adapter` 동봉.
  워커 env 는 `LORA_PLANNER_REPO`·`LORA_CHARACTER_REPO`.
- **FastAPI AI 엔진 RunPod 상시 CPU Pod 이전 (EC2 → RunPod)**: AI 서버 배포를 EC2(SSM +
  docker-compose)에서 **RunPod Secure Cloud 상시 CPU Pod**로 이전("운영 단일화", 근거 `docs/adr/0005`).
  기존 CPU `Dockerfile`(uvicorn :8010) 재사용. `runpod_workers/setup_pod.py`(신규)로 Pod 1회 생성
  (REST `POST /v1/pods`, HTTP 8010 노출, 앱 env 주입). `deploy-api.yml` 의 deploy 잡을 EC2 SSM →
  **Pod stop→start 재시작**(컨테이너 디스크 wipe → `:latest` 재-pull)으로 교체하고 프록시
  `https://{podId}-8010.proxy.runpod.net/health` 를 폴링한다. Pod ID 고정으로 프록시 URL 안정 →
  mongle-server `MONGLE_AI_API_BASE` 는 1회 설정. ⚠️ 프록시 100s 타임아웃 — 동기 엔드포인트는
  100s 내 응답 필요(무거운 작업은 워커 위임+폴링/비동기 Job). 배포 시 GitHub Secret `RUNPOD_POD_ID` 등록 필요.
- **RunPod 이미지 워커 멀티-어댑터화 (character + bg 합본)**: 이미지 워커를 LLM 과 동일한
  멀티-어댑터 구조로(설정된 어댑터만 등록, `input.adapter`로 분기) 만들어 한 엔드포인트에서
  **character**(사진→픽셀아트 스프라이트, SDXL+ControlNet img2img)와 **bg**(텍스트→배경 장면,
  SDXL text2img + LCM 8-step)를 모두 서빙한다. 모드별 파일 분리(`character_mode.py`·`bg_mode.py`),
  env `LORA_CHARACTER_REPO`·`LORA_BG_REPO`(`Hadimeeee/mongle-character-lora`·`mongle-bg-lora`).
  character LoRA 를 공식 `mongle-character-lora`(트리거 `monglestyle`, 30-step, ControlNet 0.75)로
  교체. 오케스트레이터 `runpod_image` 는 payload 에 `adapter="character"` 동봉. bg 의 feed
  파이프라인 배선은 후속(feed 는 아직 미배선). 각 모드는 독립 SDXL 로드(`from_pipe` 공유는 후속 최적화).
- **FastAPI 마이그레이션**: Streamlit 진입점을 제거하고 stateless FastAPI AI 엔진(`api/`)으로 대체.
  Django + React 웹이 X-API-Key 인증으로 5개 엔드포인트(todo generate/chat/commit, quest, character)를 호출.
  `agents/` 도메인 코드는 변경 없음 — 어댑터 교체로만 stateless 전환 (근거: `docs/adr/0001`~`0005`).
  feed_generation 엔드포인트는 img2img/S3 어댑터 미비로 후속 작업으로 분리.
- TODO/quest 런타임 LLM 경로에서 `fake` fallback 제거. FastAPI 설정과 ports 빌더는 이제 `qwen`만 허용하며, 테스트는 런타임 어댑터 대신 테스트 내부 fake로 분리.

### Added
- **sft_pipeline 언어 게이트 (중국어 응답 근본 원인 수정)**:
  - 파인튜닝 모델이 간헐적으로 중국어로 응답하던 문제의 원인 확정: teacher(Qwen 14B) 합성분의
    code-switching 혼입 — exam_synth 17.6%(176/1000)·daily ~2%(각 1000행 중 20행 내외)가
    `"…획득为目标，聚焦高频考点…"` 식으로 한국어→중국어 전환된 채 학습됨(학습셋의 ~8.5%).
  - `build/validate_dataset.py` 1층에 언어 게이트 신설: 금지 스크립트(가나·키릴·태국 문자) 즉시 오류,
    한자는 한국어 병기 허용을 위해 비율 임계(공백 제외 문자의 2% 초과) 적용. 침묵 패치 없이 드롭 + 사유 로그.
  - S3 합성분 3종을 게이트로 드롭해 클린셋 생성(daily 979/980행, exam_synth 821행, 위반 0건 재검증).
    원본 보존, `*_clean.jsonl` 별도 보관.
- **sft_pipeline 구조화 플랜 출력 전환 (정합성 우선)**:
  - SFT 목표를 멀티턴 대화력 → **출력 구조·정합성**으로 재정의. assistant 출력을 자유 텍스트에서 런타임 `GenerateResult` 미러 JSON(`summary_text`/`todos`/`calendar_events`)으로 전환.
  - `build/plan_schemas.py` 신설: `PlanTask`/`PlanOutput`(런타임 `agents/todo_creation/schemas.py` 미러 + 동기화 테스트) + `parse_plan`/`check_plan_consistency`(날짜 범위·C5 분기·분량·'N단원/N일차' 단조 분해 과반 reject).
  - exam 빌드(`build/templates.py`): 페이즈 구조(개념→기출→오답→총정리) 분해 + 크롤 전략(`actual_plan_summary`)을 `summary_text` 에 그라운딩. `--today` 기준일 앵커를 input·meta 에 기록. LLM 재서술은 `summary_text` 만 대상.
  - latte 합성(`latte/synthesize.py`): 멀티턴 잡담 → **단일턴 '요청→구조화 플랜'** 재설계. LLM 출력이 스키마·정합성 검증 실패 시 템플릿 폴백(reject & fallback).
  - `build/validate_dataset.py`: 1층 형식 검사(messages) + 2층 플랜 정합성(스키마 파싱·`meta.today` 앵커·horizon·분기·단조 분해) 2단 검증으로 확장.
  - 오프라인 end-to-end(structure → build → synthesize → mix internal/public → validate, 32건 ok=32 errors=0) 통과.
- **sft_pipeline 일상(MS-LaTTE) 멀티턴 확장 + messages 포맷 통일**:
  - SFT 출력 스키마를 단일턴(`instruction/input/output`)에서 `{messages:[...], meta}` 로 통일. 시험 단일턴은 user→assistant 2턴으로 마이그레이션, `meta.provenance`(`exam-crawl`/`daily-latte`)·`turn_type` 추가. `validate_dataset` 은 messages 스키마 + provenance 조건부 메타 검증으로 갱신.
  - `sft_pipeline/latte/` 신설: `download`(MS-LaTTE.json SHA 고정 취득, MIT) → `parse`(어노테이터 다수결 집계) → `localize`(위치 59종·시간대 한국어 결정론 매핑) → `synthesize`(한국어 멀티턴 합성, OpenAI 호환 base_url 로 로컬 오픈모델 + 템플릿 폴백).
  - `build/mix_dataset.py`: release 정책 믹스. **저작권상 시험-크롤(라이선스 없는 블로그 기반)은 `public` 배포판에서 provenance 기준 자동 제외**, 일상(MIT)만 공개. `internal` 은 전체 포함.
  - `data/sources/` gitignore(외부 원본 비커밋). 오프라인 end-to-end(parse 10,101 → localize → synthesize 템플릿 → mix → validate) 통과.
- **캐릭터 이미지 생성 RunPod Serverless 분리** (`IMAGE_PROVIDER=local|runpod`):
  - `adapters/character_creation/runpod_image`: RunPod `/run`+`/status` 폴링 어댑터 (일시 오류 내성 3회, 타임아웃/포기 시 `/cancel` 로 GPU 중복 과금 방지, 기본 타임아웃 600s).
  - `runpod_workers/image_gen/`: SDXL+ControlNet+LoRA+rembg Serverless 워커 (Dockerfile 에 공개 모델 fp16 베이크, LoRA 는 런타임 `LORA_REPO_ID`+`HF_TOKEN` 로드).
  - `api/config.py`/`api/deps.py`: provider 분기 — runpod 면 `RUNPOD_IMAGE_ENDPOINT_URL`/`RUNPOD_API_KEY` 필수, `LORA_DIR` 불필요. 배포(EC2 CPU 인스턴스)에서 GPU 없이 캐릭터 생성 가능.
- **S3 presigned URL 리전 엔드포인트 고정**: `_s3_client` 가 `endpoint_url` 을 리전형으로 명시 — 글로벌 엔드포인트로 presigned 생성 후 GET 시 307 리다이렉트되며 SigV4 서명(SignedHeaders=host)이 깨져 403 나던 회귀 방지.
- **TODO 생성 Qwen 전용화 + persona 어댑터 분리**: `_build_todo_llm` 을 항상 Qwen(planning 어댑터)으로 고정. `api/deps.py` 가 (qwen 마이그레이션 23628c7 에서 삭제된) `todo_creation/openai_llm` 을 import 해 FastAPI 기동이 깨지던 회귀를, 파일 복원 대신 openai 분기 제거로 해결. character 는 `QWEN_PERSONA_MODEL` 로 persona 어댑터를 planning 과 분리(미설정 시 `QWEN_MODEL` 폴백).
- `adapters/todo_creation/qwen_llm`: `Qwen/Qwen2.5-7B-Instruct` 전용 TODO 생성 어댑터. OpenAI-compatible 서버는 HTTP로 직접 호출하고, raw JSON 파싱·코드펜스 제거·스키마 재강화 1회 재시도를 제공.
- `tools/todo_qwen_console.py`: Streamlit 없이 Qwen TODO 프롬프트를 입력하고 messages/raw/parsed 출력을 확인하는 콘솔 도구.
- `agents/quest_generation`: 캐릭터 퀘스트 분배 에이전트 (1:1:1 매핑, 라운드 풀, LLM 2회 재시도, TODO 내용 격리). 상세: `docs/features/quest_generation/CLAUDE.md`, 설계 결정: `docs/superpowers/specs/2026-05-25-quest-generation-design.md`.
- `adapters/todo_creation/quest_dispatch_adapter`: 위 에이전트를 commit 파이프라인의 `QuestDispatchPort` 에 연결 (오늘 TODO·활성 캐릭터 fetch → 에이전트 호출 → quests 영속화).
- `adapters/{character_creation,quest_generation,feed_generation}/qwen_llm`: Qwen 7B 기반 텍스트 생성 어댑터. JSON 강제 파싱·코드펜스 제거·스키마 재강화 재시도를 각 피처 계약에 맞게 제공.
- `streamlit_app/ports_factory`: `QWEN_*` 환경변수 wiring. TODO/캐릭터/퀘스트 텍스트 생성이 Qwen 7B 어댑터를 사용하도록 전환.
- **multi_turn TODO/플랜 챗봇** (`agents/todo_creation/multi_turn/`):
  - Hybrid LangGraph (정보수집=결정론, 수정루프=tool-calling)
  - SessionStorePort + InMemorySessionStore (Port 확정, MySQL 어댑터는 후속)
  - 9 노드 + RetryPolicy + C3 재생성+truncate fallback
  - FakeMultiTurnLLM (큐 기반) + 통합 시나리오 5개
  - OpenAIMultiTurnLLM 어댑터 + gated contract test
  - 설계서: `docs/superpowers/specs/2026-05-25-todo-multiturn-design.md`
- TODO singleton + commit LangGraph 파이프라인 (`agents/todo_creation/single_turn/`, `agents/todo_creation/commit/`) — 인메모리 페이크 어댑터 (`adapters/todo_creation/`) 및 OpenAI LLM 어댑터 포함. 스펙: `docs/superpowers/specs/2026-05-24-todo-singleton-commit-design.md`.
- `agents/character_creation/` 초기 구현 — Validation → Router → LLM·VLM·S3 업로드 (병렬) → 이미지 생성 → 빌드 파이프라인. 외부 의존은 Protocol 포트로 추상화, 테스트는 인메모리 페이크로 검증 (커버리지 80%+).
- `agents/character_creation/` 파이프라인을 LangGraph `StateGraph` 기반으로 재구현. 노드별 retry 는 `RetryPolicy` 로 이관(`llm_persona` 3회, `source_upload`/`generated_upload` 4회, `image_generator` 2회), `vlm_analyzer` 만 None 폴백을 위해 노드 내부 3회 retry 유지. source 이미지 cleanup 은 compensation 노드 `cleanup_source_image_node` 로 분리. `pipeline.run()` 외부 시그니처와 모든 통합 테스트(7건) 호환성 유지. 신규 파일: `graph.py`, `state.py`, `nodes/{validate,source_upload,generated_upload,cleanup}.py`. 의존성: `langgraph>=0.2,<0.3` 추가. as-built 다이어그램: `docs/features/character_generation/architecture.mmd` 갱신.
- 피처 결정사항 `agents/character_creation/decisions.md` 신규 — 포트 분리, 에이전트 순수성, cleanup 책임, VLM degrade-on-fail.
- `docs/features/character_generation/architecture.mmd` as-built 갱신 (재시도 횟수 / VLM 옵셔널 / img_gen_logs 카운터 표기).
- Streamlit UI (`streamlit_app/app.py`) for `character_creation` agent, with real OpenAI (gpt-4o + gpt-image-1) and AWS S3 adapters under `adapters/character_creation/`. Run via `pip install -e ".[ui]"` + `streamlit run streamlit_app/app.py`. Adapters tested with 23 unit tests (memory_repo, s3_storage, openai_llm, openai_vlm, openai_image).

### Changed
- 텍스트 LLM 경로를 Qwen 중심 환경변수(`QWEN_BASE_URL`, `QWEN_MODEL`, `QWEN_API_KEY`, `QWEN_TEMPERATURE`, `QWEN_MAX_TOKENS`)로 전환하고 기존 로컬 LLM 전용 어댑터/환경변수/공통 유틸을 제거.
- `agents/character_creation/`: validation 책임 분리. C1(보유 상한)·C2(일일 재생성 제한)을 에이전트에서 제거하고 백엔드(호출자) 책임으로 이전. `nodes/validate.py` 는 이제 C3·C4(이미지 MIME/크기)와 라우팅 결정만 담당하며 레포지토리에 접근하지 않는다. `CharacterRepositoryPort` 에서 `count_active`·`today_regen_count` 제거(`increment`·`save` 만 노출). `CharacterGraphState`·`pipeline.run()`·`debug.log_start()` 에서 `is_regeneration` 파라미터 제거. Streamlit 사이드바의 보유/재생성 카운터는 UI 메트릭으로만 유지(`adapters/character_creation/memory_repo.py` 의 `count_active`·`today_regen_count` 는 그대로). `docs/features/character_generation/CLAUDE.md` §3·§4.1·§5.2 동기화. 백엔드 사전 검증은 `docs/TODO.md` 백로그 항목으로 이관.
- `docs/features/character_generation/CLAUDE.md` §8 "미결 사항" → "결정 사항" 으로 갱신.
- 프로젝트 의존성·테스트 도구 정의: `pyproject.toml` 신규 (pydantic≥2, pytest + asyncio + cov, 커버리지 게이트 80%).
- `agents/character_creation/`: `vlm_skip` 더미 노드 제거. text-only 경로가 `vlm_analyzer` 로 직접 진입하고, `vlm_analyzer_node` 가 `source_image is None` 일 때 즉시 `{"vlm_result": None}` 을 반환해 `image_generator` fan-in 을 만족시킨다. `router.decide()`, `graph.build_graph()`, `architecture.mmd`, `docs/features/character_generation/CLAUDE.md` §5.1/§5.2 동기화. 신규 테스트: `test_vlm_analyzer_returns_none_without_calling_vlm_when_no_source_image`.

## [2026-05-22]
### Added
- 문서 하네스 4축 구조 정립 — `docs/PRODUCT_SPEC.md`, `docs/FEATURES.md`, `docs/AI_RULES.md` 신규 작성 (`docs/DATA_MODEL.md` 무수정 유지)
- 라우팅 허브 — `CLAUDE.md` 를 작업별 문서 라우팅 테이블 + 체크리스트로 재작성
- `CHANGELOG.md` 신규 도입 (본 파일)
- 완성 정의(DoD) 명문화 — `docs/FEATURES.md` §4
- `docs/features/{character_generation,todo,quest_generation,feed_generation}/CLAUDE.md` 4건에 상위 문서 역참조 헤더 부착
- `docs/TODO.md` 를 내부 작업·결정 로그 포맷으로 재초기화

### Changed
- 프로젝트 루트 `CLAUDE.md` 의 일반 LLM 코딩 가이드(글로벌 룰과 중복) 제거 → 라우팅 허브로 대체
