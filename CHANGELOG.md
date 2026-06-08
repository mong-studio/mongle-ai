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

### Fixed
- **SFT LoRA 학습 `<EOS_TOKEN>` 반복 실패 해결**: `train_lora.py`가 `trl`을 `unsloth`보다 먼저 import해
  unsloth의 trl 몽키패치가 어긋나며 `eos_token`이 `<EOS_TOKEN>` placeholder로 새어 학습이 죽던 문제.
  **import 순서를 unsloth 우선으로 재배치**해 근본 해결(transformers 5.5.0 그대로, 다운그레이드 불필요).
  진단·오판 경로·재현 절차는 `sft_pipeline/train/TROUBLESHOOTING.md`. 근거: unsloth#2797 (maintainer:
  "always import unsloth first"). 검증: RTX 4090에서 Qwen2.5-7B QLoRA 2epoch 정상 수렴(loss 1.33→0.21).

### Changed
- **SFT 플랜 출력에서 `tags` 필드 제거 (학습 토큰 다이어트)**:
  - 태그는 별도 Tagger 노드 책임(todo CLAUDE.md §4.9, 어휘 체계 미결)이라 플랜 SFT 가 배울
    토큰이 아님 — `["공부"]` 류 저정보 토큰이 전 항목에 반복되던 것을 제거.
  - `plan_schemas.dump_plan_for_training` 신설(tags 제외 직렬화, PlanTask 스키마는 런타임
    미러 유지). 빌더 3종(exam_synth·templates·latte/synthesize) 출력·프롬프트 예시,
    sft_qwen_llm 어댑터 재강화 프롬프트에서 일괄 제거 — 학습/서빙 토큰 시퀀스 동시 전환.
  - `build/strip_tags.py` 신설(멱등): 기생성 클린셋 3파일(exam 12·daily_v1 979·daily_v2 980)
    in-place 마이그레이션, distractor(chat) 0건 무변경, 신 검증기 전건(ok=2273) 통과.
    파싱 폴백(`item.get("tags") or []`)과 런타임 `TaskCandidate.tags` default 는 유지 — 호환 보장.
- **SFT meta 스키마에 `task_type` 도입 (plan/chat 분기의 명시 축)**:
  - validate 2층(플랜 정합성) 분기를 `PLAN_PROVENANCES` 집합(provenance 간접 유추)에서
    `meta.task_type`(`"plan"|"chat"`, 필수+화이트리스트) 명시 필드로 전환. 소비처 4곳 일괄 전환
    (`validate_dataset`·`coherence_eval`·`train/postcheck`·`train/train_plain`).
  - meta 정리: `turn_type` 제거(전 샘플 single 상수·소비처 0), `is_distractor` 제거(provenance 중복),
    `rephrased_by`→`synthesized_by` 이름 통일. distractor `label`은 계보 보존용 주석 명시.
  - `build/migrate_meta.py` 신설(멱등·messages 불변): 기존 클린셋 4파일(exam 12·daily_v1 979·
    daily_v2 980·distractor 302) in-place 마이그레이션, 신 검증기 전건 통과. exam_synth 는
    구조 인지형 빌더 재합성으로 대체 예정이라 마이그레이션 제외.
- **FastAPI 마이그레이션**: Streamlit 진입점을 제거하고 stateless FastAPI AI 엔진(`api/`)으로 대체.
  Django + React 웹이 X-API-Key 인증으로 5개 엔드포인트(todo generate/chat/commit, quest, character)를 호출.
  `agents/` 도메인 코드는 변경 없음 — 어댑터 교체로만 stateless 전환 (근거: `docs/adr/0001`~`0005`).
  feed_generation 엔드포인트는 img2img/S3 어댑터 미비로 후속 작업으로 분리.

### Added
- **플랜 제목 길이 20→30자 상향 (시험 과목·파트명 수용)**:
  - 시험 과목명(예: '정보시스템 구축 관리')+행동 조합이 20자를 구조적으로 초과해 LLM 합성분의
    상당수가 길이 검증에서 폴백되던 문제. 구조적 상한 26자 + 회독 표기 여유로 30자 채택.
  - 런타임 `TaskCandidate.title`·미러 `PlanTask.title` `max_length` 20→30(확대=하위호환),
    동기화 테스트·`_phase_title` 상한 갱신. 프롬프트에 군더더기('N문항'·'및 검토'·'다시 풀이')
    금지 지시 병행(길이만 늘리면 췌언 제목이 남으므로).
  - **DB 마이그레이션 필요(웹팀)**: `todos.content`·`schedules.title` `VARCHAR(20)→VARCHAR(30)`,
    React 입력/표시 제약 동반 상향. `docs/DATA_MODEL.md` 갱신 완료, 실제 ALTER 는 별도.
- **exam_synth 시간축 분해를 phase×section 으로 (일정 분해 논리 강화)**:
  - 기존 폴백/프롬프트가 과목을 1열로 나열(목차 나열)해 학습 단계·회독 개념이 없고 기간(D-7 vs
    D-60) 차등이 없던 문제 수정. plan-coherence M1(분배 합리성)·M3(순서 논리) 대응.
  - `_PHASE_PLANS` 도입: 기간별 학습 단계 시퀀스(개념→기출→약점→모의→점검)를 골격으로,
    ~D-9 벼락치기는 기출 2회독+모의로 압축, D-17+ 는 개념+기출 2회독 풀 사이클. 각 단계 안에서
    과목/파트를 펼치고(per_section), 단계 순서가 곧 날짜 순서.
  - `_fallback_plan` 재작성 + 프롬프트에 단계 시퀀스 지시 추가. JLPT section 키워드 친화 표기,
    `_section_core`(번호·괄호 접두 제거)로 제목 20자 보존. 전수(9종×6기간) 정합성·구체성≥0.6 통과.
- **exam_synth 구조 인지형 플랜 전환 + 어학 시험 확장 (추상 플랜 근본 원인 수정)**:
  - 기존 합성분의 플랜 제목 97.1%(8,336/8,586 항목)가 "약점 보완"·"기출 문제 회독" 류 추상 문구였던
    원인 확정: 합성 프롬프트가 '1단원/2단원 기계적 분해'를 금지하며 과목·범위 참조까지 차단(과교정).
  - `config/exam_structures.yaml` 신설: 시행기관 공식 출처(큐넷·ETS·국편위·Kdata·대한상의·OPIc·JLPT)
    기반 시험 9종 과목/파트 구조 큐레이션(출처 URL·확인일 명기) + 크롤 코퍼스 마이닝 현실 표현 키워드.
  - `build/exam_synth.py`: 프롬프트에 시험 구조 주입, 구체성 게이트 신설(과목/파트 키워드 포함 title
    비율 < 0.6 reject → 폴백), 폴백 템플릿을 구조 기반으로 재작성(`PlanTask.title` 20자 제약 준수).
  - 시험 종류 확장: 오픽·토플·JLPT 추가 (별칭 매핑 + 난이도 스펙트럼). 단, 크롤 그라운딩 없음 →
    재합성 후 게이트 통과율 모니터링 대상.
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
