# CHANGELOG

본 프로젝트의 주요 변경사항을 기록한다. 포맷은 [Keep a Changelog 1.1.0](https://keepachangelog.com/ko/1.1.0/) 을 따른다.

> **이 파일은 팀 공유용이다.** 내부 작업·결정 로그는 `docs/TODO.md` 를 사용한다.
>
> **갱신 규칙:** 파이프라인을 만들거나 변경할 때마다 항목을 추가한다. 완성 정의는 `docs/FEATURES.md` §4 참조.

## [Unreleased]
### Added
- TODO singleton + commit LangGraph 파이프라인 (`agents/todo_creation/single_turn/`, `agents/todo_creation/commit/`) — 인메모리 페이크 어댑터 (`adapters/todo_creation/`) 및 OpenAI LLM 어댑터 포함. 스펙: `docs/superpowers/specs/2026-05-24-todo-singleton-commit-design.md`.
- `agents/character_creation/` 초기 구현 — Validation → Router → LLM·VLM·S3 업로드 (병렬) → 이미지 생성 → 빌드 파이프라인. 외부 의존은 Protocol 포트로 추상화, 테스트는 인메모리 페이크로 검증 (커버리지 80%+).
- `agents/character_creation/` 파이프라인을 LangGraph `StateGraph` 기반으로 재구현. 노드별 retry 는 `RetryPolicy` 로 이관(`llm_persona` 3회, `source_upload`/`generated_upload` 4회, `image_generator` 2회), `vlm_analyzer` 만 None 폴백을 위해 노드 내부 3회 retry 유지. source 이미지 cleanup 은 compensation 노드 `cleanup_source_image_node` 로 분리. `pipeline.run()` 외부 시그니처와 모든 통합 테스트(7건) 호환성 유지. 신규 파일: `graph.py`, `state.py`, `nodes/{validate,source_upload,generated_upload,cleanup}.py`. 의존성: `langgraph>=0.2,<0.3` 추가. as-built 다이어그램: `docs/features/character_generation/architecture.mmd` 갱신.
- 피처 결정사항 `agents/character_creation/decisions.md` 신규 — 포트 분리, 에이전트 순수성, cleanup 책임, VLM degrade-on-fail.
- `docs/features/character_generation/architecture.mmd` as-built 갱신 (재시도 횟수 / VLM 옵셔널 / img_gen_logs 카운터 표기).
- Streamlit UI (`streamlit_app/app.py`) for `character_creation` agent, with real OpenAI (gpt-4o + gpt-image-1) and AWS S3 adapters under `adapters/character_creation/`. Run via `pip install -e ".[ui]"` + `streamlit run streamlit_app/app.py`. Adapters tested with 23 unit tests (memory_repo, s3_storage, openai_llm, openai_vlm, openai_image).

### Changed
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
