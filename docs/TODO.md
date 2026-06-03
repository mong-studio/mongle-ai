# 작업 로그 (내부)

> 본 파일은 **내부 완료 작업·결정 사항** 을 기록한다.
> 팀 공유용 변경사항은 [`../CHANGELOG.md`](../CHANGELOG.md) 를 사용한다.

## 완료

- [x] 2026-05-22 — 문서 하네스 4축 구조 정립 (PRODUCT_SPEC / FEATURES / AI_RULES / DATA_MODEL + CLAUDE.md 라우팅)
- [x] 2026-05-22 — DATA_MODEL.md 15 테이블 정의
- [x] 2026-05-22 — 4개 피처 설계서 작성 (character_generation, todo, quest_generation, feed_generation)
- [x] 2026-05-22 — CHANGELOG.md 도입 + DoD 명문화
- [x] 2026-05-22 — character_creation 에이전트 초기 구현 (포트 분리 / TDD / 커버리지 80%+ / 피처 §8 미결 사항 5건 해소)

## 진행 중

- (없음)

## 백로그 (내부 메모)

- [ ] **(backend)** character_creation 진입 전 C1(보유 ≤10)·C2(일일 재생성 ≤3) 검증을 백엔드/호출자에서 강제. 현재 Streamlit 사이드바는 카운터만 표시하고 차단하지 않으므로 실제 백엔드 연결 시 사전 거부 로직 필요. 에이전트는 더 이상 이 규칙을 알지 못한다 (`CharacterRepositoryPort` 에서 관련 메서드 제거됨).

- [ ] **(api)** FastAPI 서비스로 에이전트 파이프라인 노출 — 4개 피처(character_creation / todo_creation[single_turn·commit·multi_turn] / quest_generation / feed_generation) 의 `async def run(...)` 진입점을 HTTP 라우터로 래핑. Streamlit 과 병존.
  - 재사용: `streamlit_app/ports_factory.py` 의 `AppConfig.from_env()` + `build_*_ports(cfg)` 빌더 → FastAPI `Depends` 로 이식. 누락된 `build_feed_ports`, `build_quest_ports` 분리 추가 필요.
  - 디렉토리: `api/{main,deps,auth,errors,logging}.py` + `api/routers/{character,todo,quest,feed}.py` + `tests/api/`.
  - 인증: Bearer 토큰 (`API_TOKEN` / `API_TOKENS` 환경변수, 상수시간 비교). 헬스체크 제외.
  - 에러 매핑: `MissingEnvError → 500`, `FeedGenerationError`·`LLMFailedError → 502`, 도메인 ValidationError → 400, Pydantic ValidationError → 422 (기본).
  - 미들웨어: `X-Request-ID` 에코, JSON 구조화 로그, CORS, 라이프스팬에서 `AppConfig` 1회 로딩.
  - 응답 모델: 도메인 스키마 그대로 노출하지 말고 명시적 Pydantic 응답 모델 사용(내부 필드 유출 방지).
  - 테스트: `httpx.AsyncClient(ASGITransport)` + fake LLM/in-memory storage fixture. 라우터별 happy / unauthorized / invalid input / pipeline failure 4종. `pyproject.toml` 에 별도 `--cov=api` 측정.
  - 배포: 멀티스테이지 Dockerfile (`python:3.11-slim` + uv `--extra api`), `HEALTHCHECK /healthz`, uvicorn `--factory`.
  - 의존성 추가: `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `httpx>=0.27` → `[project.optional-dependencies] api`.
  - 의사결정 보류: (a) `InMemoryRepo` 를 앱 단일 인스턴스 공유(현재 데모 가정) vs 요청별 격리 — 1차는 단일 인스턴스, 후속 PR에서 DB 어댑터로 교체. (b) 긴 LLM/이미지 호출에 대한 SSE 스트리밍·백그라운드 큐는 본 작업 범위 밖.
  - 범위 밖 (후속): SSE 스트리밍, BackgroundTasks/Celery 큐, 레이트리밋, OTel/Sentry, CI/CD, K8s 매니페스트.
  - 예상 공수: 약 17h (2~3 영업일). PoC(스캐폴드+Depends+인증+happy path) 만 분리 시 4~5h.
  - 완료 후 갱신: `CLAUDE.md` 라우팅 표에 "API 서버 작업" 행 추가, `README.md` 실행 섹션, `CHANGELOG.md` 항목 추가.
