# 몽글마을 — Codex 가이드 (라우팅 허브)

> 본 파일은 **작업 종류에 따라 어떤 문서를 읽어야 하는지** 매핑하는 라우팅 허브다.
> 일반 코딩 스타일·테스트·보안 정책은 글로벌 룰 (`~/.Codex/rules/*`) 을 따른다.

## 1. 핵심 원칙 (요약)

- **Think Before Coding** — 가정하지 말고 확인. 모호하면 질문.
- **Simplicity First** — 최소 코드로 해결. YAGNI.
- **Surgical Changes** — 외과적 변경. 요청한 부분만 건드린다.
- **Goal-Driven Execution** — 검증 가능한 성공 기준 → 통과할 때까지 루프.

자세한 원칙은 `~/.Codex/rules/coding-style.md` 등 글로벌 룰 참조.

## 2. 문서 라우팅 테이블

**작업 시작 전, 아래 표에서 해당 행을 찾아 명시된 문서를 모두 읽는다.**

| 작업 종류                                 | 반드시 읽을 문서                                                                                           |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| **(신규 합류자) 처음 보는 사람**          | `docs/PRODUCT_SPEC.md` → `docs/FEATURES.md` → `docs/DATA_MODEL.md` (도메인 그룹표) → 관심 피처 `AGENTS.md` |
| 신규 피처 시작·범위 확인                  | `docs/PRODUCT_SPEC.md`, `docs/FEATURES.md`                                                                 |
| AI 에이전트 코드 작성 (LLM/VLM 호출 포함) | `docs/AI_RULES.md` (**항상**) + 해당 피처 행 추가 적용                                                     |
| 캐릭터 생성 관련                          | `docs/features/character_generation/AGENTS.md`, `docs/DATA_MODEL.md` §2                                    |
| TODO/플랜 관련                            | `docs/features/todo/AGENTS.md`, `docs/DATA_MODEL.md` §3                                                    |
| 퀘스트 분배 관련                          | `docs/features/quest_generation/AGENTS.md`, `docs/DATA_MODEL.md` §2, §3.2                                  |
| 피드 생성 관련                            | `docs/features/feed_generation/AGENTS.md`, `docs/DATA_MODEL.md` §2, §4                                     |
| 회고 관련                                 | `docs/DATA_MODEL.md` §5, `docs/PRODUCT_SPEC.md`                                                            |
| SNS(댓글/답글) 관련                       | `docs/DATA_MODEL.md` §4.2, §4.3                                                                            |
| 태그 시스템 관련                          | `docs/DATA_MODEL.md` §3.4, `docs/features/todo/AGENTS.md` §4.9                                             |
| DB 스키마 추가·변경                       | `docs/DATA_MODEL.md` (전체)                                                                                |
| 인증·토큰·알림                            | `docs/PRODUCT_SPEC.md`, `docs/DATA_MODEL.md` §1, §6                                                        |
| 파이프라인 구현·완성·릴리스               | `CHANGELOG.md`, `docs/features/{feature}/architecture.mmd`, `docs/FEATURES.md` §4 (DoD)                    |

## 3. 작업 전 체크리스트

- [ ] 위 라우팅 표에서 해당 작업의 문서를 모두 읽었다.
- [ ] DB 변경이 포함된다면 `docs/DATA_MODEL.md` 의 관련 테이블 제약을 확인했다.
- [ ] AI 호출이 포함된다면 `docs/AI_RULES.md` 의 모델·재시도·언어·격리·보안 규칙을 따랐다.
- [ ] 파이프라인을 새로 만들거나 변경했다면 `CHANGELOG.md` 에 항목을 추가했다.
- [ ] 기능을 "완성" 처리했다면 `docs/features/{feature}/architecture.mmd` 를 as-built 로 갱신했다 (DoD: `docs/FEATURES.md` §4 참조).

## 4. 디렉토리 컨벤션

코드 레이아웃:

```
agents/{feature}/
├── pipeline.py        # 오케스트레이션 entry point
├── validation.py
├── nodes/             # 단계별 노드
├── repository.py      # DB I/O
├── schemas.py         # Pydantic 모델
└── exceptions.py
```

자세한 컨벤션과 예외(복잡 피처의 하위 폴더 등): `docs/FEATURES.md` §3.4.

## 5. 관련 문서 전체 인덱스

- 제품 북극성: `docs/PRODUCT_SPEC.md`
- 피처 인덱스·DoD: `docs/FEATURES.md`
- DB 스키마: `docs/DATA_MODEL.md`
- 런타임 AI 규칙: `docs/AI_RULES.md`
- 팀 공유 변경 로그: `CHANGELOG.md`
- 내부 작업 로그: `docs/TODO.md`
- 본 작업 스펙: `docs/superpowers/specs/2026-05-22-docs-harness-design.md`
- 본 작업 계획: `docs/superpowers/plans/2026-05-22-docs-harness.md`

## 6. Setup

```bash
uv sync              # 기본 의존성 (agents/, tests/)
uv sync --extra ui   # streamlit 데모 실행 시 (langchain-openai, openai, streamlit 등)
```

> UI 작업 진입 시 `ModuleNotFoundError: No module named 'langchain_openai'` 가 나면 `--extra ui` 누락이다.

실행:
```bash
uv run streamlit run streamlit_app/app.py
```
