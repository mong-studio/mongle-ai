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

### Changed
- **FastAPI 마이그레이션**: Streamlit 진입점을 제거하고 stateless FastAPI AI 엔진(`api/`)으로 대체.
  Django + React 웹이 X-API-Key 인증으로 5개 엔드포인트(todo generate/chat/commit, quest, character)를 호출.
  `agents/` 도메인 코드는 변경 없음 — 어댑터 교체로만 stateless 전환 (근거: `docs/adr/0001`~`0005`).
  feed_generation 엔드포인트는 img2img/S3 어댑터 미비로 후속 작업으로 분리.

### Added
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
