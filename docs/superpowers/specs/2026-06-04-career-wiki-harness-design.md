# Career Wiki Harness — 설계

> 상태: 승인됨 (브레인스토밍 → 설계). 다음 단계: 구현 계획(writing-plans).
> 날짜: 2026-06-04
> 참조: Karpathy "LLM Wiki" 패턴 (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

## 1. 목적

Claude Code 세션 안에서만 휘발되는 **트러블슈팅 기록·기술적 의사결정**을, 추후 이력서·포트폴리오에
재사용 가능한 형태로 Obsidian 볼트에 누적한다. RAG처럼 질의 가능해야 한다.

핵심 통찰(Karpathy 모델): 원본을 매 질의마다 RAG로 재발견하지 않고, LLM이 **상호 연결된 마크다운 위키**를
점진적으로 유지해 지식이 세션을 넘어 **누적**되게 한다. 중립 사실(Decisions)과 이력서 서사(Portfolio)를
분리하되 `[[링크]]`로 엮는다.

## 2. 범위

- **크로스프로젝트 커리어 볼트**: mongle-ai 등 모든 프로젝트의 결정을 하나의 Obsidian Vault에 모은다.
- 도구는 **전역**(`~/.claude/`)에 둔다. 특정 레포를 오염시키지 않는다.
- 비범위(YAGNI): 벡터 임베딩, 자동 이력서 PDF 생성, 다중 볼트 동기화.

## 3. 데이터 모델 (볼트 구조)

볼트: `/Users/jpaper/Documents/Obsidian Vault/`

```
Career Wiki/
├── 00 Schema.md          # 위키 자신의 규칙서 (LLM이 따르는 'CLAUDE.md')
├── 00 Index.md           # 자동 유지되는 카탈로그 (Map of Content)
├── Decisions/            # 중립 기술 기록 (ADR·트러블슈팅 고도)
│   └── 2026-06-04-fastapi-stateless-boundary.md
├── Portfolio/            # STAR 서사 (이력서 지향)
│   └── stateless-ai-service-migration.md
├── Projects/             # 프로젝트별 엔티티 페이지
│   └── mongle-ai.md
├── Tech/                 # 기술·패턴·개념 엔티티 페이지
│   ├── fastapi.md
│   └── adapter-pattern.md
└── _Inbox/               # Stop 훅이 떨군 검토 대기 후보
    └── 2026-06-04-session-candidates.md
```

`Career Wiki/` 상위 폴더로 감싸 자기완결성을 확보한다(볼트가 향후 다른 용도로 확장돼도 충돌 없음).

### 3.1 페이지 타입

| 타입 | 폴더 | 역할 | 본문 골격 |
|------|------|------|-----------|
| **Decision** | `Decisions/` | 중립적 사실 기록(진실의 출처). `type: decision`/`troubleshooting` 구분 | Context · Problem · Options · Decision · Consequences · Evidence(PR/commit/ADR 링크) |
| **Portfolio** | `Portfolio/` | 이력서용 STAR 서사. Decision들을 인용·링크 | Situation · Task · Action · Result · **Resume bullet 한 줄** |
| **Project** | `Projects/` | 프로젝트 엔티티(역할·스택·핵심 결정 MOC) | 개요 · 내 역할 · 스택 · 관련 Decision/Portfolio 링크 |
| **Tech** | `Tech/` | 기술·패턴 엔티티(어디서 썼나·배운 점) | 정의 · 사용처 링크 · 배운 점/함정 |

### 3.2 Frontmatter 규약 (예시)

Decision:
```yaml
---
type: decision        # 또는 troubleshooting
date: 2026-06-04
project: "[[mongle-ai]]"
tech: ["[[fastapi]]", "[[adapter-pattern]]"]
status: accepted      # proposed | accepted | superseded
tags: [decision, architecture, fastapi]
evidence: [PR#42, "docs/adr/0001-..."]
portfolio: "[[stateless-ai-service-migration]]"
---
```

Portfolio:
```yaml
---
type: portfolio
skills: [system-design, fastapi, migration]
impact: "상태 비저장 경계 도입으로 배포 단순화"   # 날조 금지: 검증 가능한 것만
role: "백엔드/AI 파이프라인"
backed_by: ["[[2026-06-04-fastapi-stateless-boundary]]"]
tags: [portfolio, backend]
---
```

### 3.3 링크·태그 규약

- 페이지 간 연결은 `[[kebab-case-slug]]`.
- Decision 파일명은 `YYYY-MM-DD-<slug>.md` (시간순 정렬).
- 엔티티(Project/Tech) 파일명은 날짜 없는 `<slug>.md`.
- 태그: `#decision #troubleshooting #portfolio` + 기술 태그.
- **메트릭 날조 금지**: Portfolio의 impact/숫자는 evidence로 뒷받침되는 것만 기재.

## 4. 도구 구성 (전역, `~/.claude/`)

### 4.1 스킬 `career-wiki` (`~/.claude/skills/career-wiki/SKILL.md`)
방법론의 단일 소스. 볼트 경로 + 페이지 템플릿 + 4개 연산 워크플로우를 담는다.
"이거 위키에 정리해줘" 류 발화에 자동 발동. 슬래시 커맨드들은 이 스킬을 얇게 호출한다.

### 4.2 슬래시 커맨드 4개 (`~/.claude/commands/`)

| 커맨드 | 하는 일 |
|--------|---------|
| `/wiki-log` | **현재 세션**의 결정/트러블슈팅 컴파일 → Decision 작성 + Portfolio STAR 갱신/생성 + Project·Tech 엔티티 갱신 + Index 갱신 |
| `/wiki-ingest <소스>` | **기존 산출물** 일괄 수집(docs/adr, 세션 요약, CHANGELOG, `PR#123`) → 동일 컴파일 파이프라인 |
| `/wiki-query <질문>` | RAG: 볼트 검색 → 인용 포함 답변 합성(벡터 없이 키워드+태그+`[[링크]]` 그래프 탐색) |
| `/wiki-lint` | 건강검진: 고아 페이지·깨진 링크·모순·오래된 주장·메트릭 누락 탐지 |

### 4.3 Stop 훅 (`~/.claude/settings.json`)
세션 종료 시 경량 동작: 세션 다이제스트(요약 + 수정 파일 + 결정 신호)를 `_Inbox/`에 **후보**로 떨군다.
Decisions/Portfolio로 **자동 편입하지 않는다** — 커리어 데이터라 사람 검토를 거친다
(`/wiki-log` 또는 inbox 리뷰 시 승격). 토글 가능.

훅 스크립트는 LLM을 호출하지 않는다(토큰·지연 회피). 실제 컴파일은 다음 `/wiki-log`가 수행한다.

### 4.4 ingest 컴파일 파이프라인 (스킬 내부 공통 로직)
```
원본(세션/ADR/PR) → 핵심 추출 → Decision 작성(중립) →
  Portfolio STAR 갱신(서사) → Project·Tech 엔티티에 [[역링크]] → Index 갱신 → lint
```

## 5. 단위 경계 (isolation)

- **00 Schema.md**: 규칙서. 다른 LLM 도구(Obsidian Copilot 등)도 이것만 읽으면 위키를 동일 규약으로 다룰 수 있다. 도구 독립적.
- **스킬**: 워크플로우 오케스트레이션. 볼트 경로 등 설정 보유.
- **커맨드**: 얇은 진입점. 스킬에 위임.
- **훅**: 캡처 버퍼만. 컴파일 책임 없음(놓침 방지 역할에 국한).

각 단위는 마크다운 인터페이스(`[[링크]]`/frontmatter)로만 소통하므로 내부 변경이 소비자를 깨지 않는다.

## 6. 성공 기준 (검증 가능)

1. `/wiki-log`를 mongle-ai의 FastAPI 마이그레이션 세션에 실행 → `Decisions/`에 중립 기록 1개 + `Portfolio/`에 STAR 1개 + `Projects/mongle-ai.md`·`Tech/fastapi.md`에 역링크 + `00 Index.md` 갱신이 생성된다.
2. `/wiki-ingest docs/adr` 실행 → 기존 ADR 0001~0005가 Decision 페이지로 들어오고 중복 없이 엔티티에 연결된다.
3. `/wiki-query "FastAPI를 왜 상태 비저장으로?"` → 해당 Decision을 인용한 답변이 나온다.
4. `/wiki-lint` → 고아/깨진 링크 0, 또는 발견 항목을 정확히 보고한다.
5. Stop 훅 → 세션 종료 후 `_Inbox/`에 후보 파일이 생긴다(자동 편입은 없다).
6. Obsidian에서 그래프 뷰가 Decisions↔Portfolio↔Project↔Tech 연결을 보여준다.

## 7. 리스크 / 결정

- **커리어 데이터의 사람 검토**: 자동 편입 대신 `_Inbox/` 후보 단계를 둔다(과장/오류가 이력서로 새는 것 방지).
- **OMC wiki 미사용 근거**: `.omc/wiki/`는 프로젝트 로컬·git-ignored·고정 카테고리라 크로스프로젝트 커리어 볼트 + STAR 레이어 요구와 충돌. 그 auto-capture 아이디어만 Stop 훅에 차용.
- **레포 비오염**: 도구 전역화. 본 설계 문서만 mongle-ai 레포에 남는다(컨벤션 위치).
