# 문서 하네스 구조 정립 — 설계서

> **작성일:** 2026-05-22
> **대상 저장소:** `mongle-village`
> **목적:** 흩어진 문서를 4축(전체 기획 / 기능 상세 / 데이터 모델 / AI 규칙) + 라우팅 허브 구조로 정리하여, Claude Code 와 팀이 작업 종류별로 정확한 문서만 선택적으로 로드·갱신할 수 있게 한다.

---

## 1. 배경 (Why)

현 상태 (2026-05-22 기준):

- `docs/PRODUCT_SPEC.md`, `docs/AI_RULES.md`, `docs/TODO.md` 모두 빈 파일.
- `docs/DATA_MODEL.md` 만 341줄로 완성됨 (15 테이블).
- `docs/features/{character_generation, todo, quest_generation, feed_generation}/CLAUDE.md` 4개가 각 6~12KB 로 상세히 작성되어 있으나, 상위 인덱스/제품 컨텍스트와 단절.
- `CLAUDE.md` (프로젝트 루트) 는 일반 LLM 코딩 가이드(라인 1~69) + 피처 포인터(라인 70~77)로 구성되어 있고, 글로벌 `~/.claude/rules/*` 와 중복되며 piece-by-piece 누락(quest/feed 미등록).
- **CHANGELOG 부재** — 팀원이 어떤 파이프라인이 살아있는지 확인할 단일 지점이 없음.
- **완성 정의(DoD) 부재** — "기능이 끝났다"의 기준이 문서화되지 않아 architecture.mmd 가 설계 시점에 멈춰 있을 위험.

이 설계는 위 다섯 문제를 한 번에 해결한다.

---

## 2. 목표 (Goals)

1. 작업 종류 → 필수 로드 문서를 1:1 매핑하는 **라우팅 테이블** 을 `CLAUDE.md` 에 둔다.
2. 4축 문서를 명확히 분리한다:
   - **`PRODUCT_SPEC.md`** = 제품 전체 스키마 (북극성)
   - **`FEATURES.md`** = 피처 인덱스 + 공통 패턴 (DoD 포함)
   - **`DATA_MODEL.md`** = DB 스키마 (현 상태 유지)
   - **`AI_RULES.md`** = 런타임 AI 운영 규칙
3. 피처 상세는 `docs/features/{feature}/CLAUDE.md` 에 그대로 두되, **상단에 표준 헤더** (상위 문서 역참조) 를 부착한다.
4. **`CHANGELOG.md`** (프로젝트 루트, Keep a Changelog 스타일) 을 도입하여 파이프라인 변경을 팀에 공유한다.
5. **DoD** 를 `FEATURES.md` 의 "공통 패턴" 섹션에 명문화하여, 기능 완성 시 architecture.mmd as-built 갱신 + CHANGELOG 항목 추가를 강제한다.
6. `docs/TODO.md` 는 **내부 완료 작업 로그** 로 유지한다 (CHANGELOG 와 역할 분리).

### Non-goals

- 글로벌 `~/.claude/rules/*` 의 코딩 스타일·테스트 정책 등은 건드리지 않는다.
- `docs/features/{feature}/CLAUDE.md` 의 본문 내용(에이전트 설계 디테일)은 재작성하지 않는다. 상단 헤더만 추가한다.
- `architecture.mmd` 파일 4개의 내용은 변경하지 않는다 (설계 시점 그대로 유지, 향후 as-built 갱신은 피처 완성 시점에 수행).
- ERD 파일 자체 (별도 도구로 관리되는 원본) 는 건드리지 않는다.

---

## 3. 최종 파일 구조

```
mongle-village/
├── CLAUDE.md                           # 라우팅 허브 + DoD 체크리스트 (대폭 축소)
├── CHANGELOG.md                        # NEW: 팀 공유 릴리스 노트
├── docs/
│   ├── PRODUCT_SPEC.md                 # NEW
│   ├── FEATURES.md                     # NEW (DoD 명문화 포함)
│   ├── DATA_MODEL.md                   # 유지 (변경 없음)
│   ├── AI_RULES.md                     # NEW
│   ├── TODO.md                         # 유지 (내부 완료 로그로 재정의)
│   └── features/
│       ├── character_generation/
│       │   ├── CLAUDE.md               # 헤더만 추가
│       │   └── architecture.mmd        # 유지
│       ├── todo/
│       │   ├── CLAUDE.md               # 헤더만 추가
│       │   └── architecture.mmd        # 유지
│       ├── quest_generation/
│       │   ├── CLAUDE.md               # 헤더만 추가
│       │   └── architecture.mmd        # 유지
│       └── feed_generation/
│           ├── CLAUDE.md               # 헤더만 추가
│           └── architecture.mmd        # 유지
```

### 삭제·교체 대상

| 대상 | 사유 |
|---|---|
| 현 `CLAUDE.md` 라인 1~69 (일반 LLM 코딩 가이드) | 글로벌 `~/.claude/rules/coding-style.md` 등과 중복. 라우팅 허브로 압축. |
| 현 `CLAUDE.md` 라인 70~77 (피처 포인터) | 라우팅 테이블로 대체. 누락된 quest/feed 보완. |

### 신규 디렉토리

- `docs/superpowers/specs/` — 본 스펙 문서를 포함한 brainstorming 산출물 저장소.

---

## 4. 파일별 상세 명세

### 4.1 `CLAUDE.md` (라우팅 허브)

**역할:** 작업 종류 → 필수 로드 문서 매핑. 핵심 원칙은 글로벌 룰에 위임하고, 본 파일은 라우팅과 DoD 체크리스트만 담는다.

**섹션:**

1. **핵심 원칙 (요약)** — 4줄 (Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution). 글로벌 가이드와 중복되지 않도록 압축.
2. **문서 라우팅 테이블** — 본 설계의 핵심.
3. **작업 전 체크리스트** — 라우팅 표 확인, DATA_MODEL 제약 확인, AI_RULES 준수, 파이프라인 변경 시 CHANGELOG/architecture.mmd 갱신.
4. **피처 디렉토리 컨벤션** — `agents/{feature}/...` 레이아웃 한 줄 안내 + FEATURES.md 링크.

**라우팅 테이블 (확정안):**

| 작업 종류 | 반드시 읽을 문서 |
|---|---|
| 신규 피처 시작·범위 확인 | `docs/PRODUCT_SPEC.md`, `docs/FEATURES.md` |
| AI 에이전트 코드 작성 (LLM/VLM 호출 포함) | `docs/AI_RULES.md` + 해당 피처 문서 |
| 캐릭터 생성 관련 | `docs/features/character_generation/CLAUDE.md`, `docs/DATA_MODEL.md` §2 |
| TODO/플랜 관련 | `docs/features/todo/CLAUDE.md`, `docs/DATA_MODEL.md` §3 |
| 퀘스트 분배 관련 | `docs/features/quest_generation/CLAUDE.md`, `docs/DATA_MODEL.md` §2~3 |
| 피드 생성 관련 | `docs/features/feed_generation/CLAUDE.md`, `docs/DATA_MODEL.md` §2,4 |
| DB 스키마 추가·변경 | `docs/DATA_MODEL.md` (전체) |
| 인증·토큰·알림 | `docs/PRODUCT_SPEC.md`, `docs/DATA_MODEL.md` §1,6 |
| 파이프라인 구현·완성·릴리스 | `CHANGELOG.md`, `docs/features/{feature}/architecture.mmd` |

**예상 분량:** 60~80줄.

---

### 4.2 `CHANGELOG.md` (신규, 프로젝트 루트)

**역할:** 팀 공유 릴리스 노트. 파이프라인을 만들거나 변경할 때마다 항목 추가.

**포맷:** Keep a Changelog 1.1.0.

```markdown
# CHANGELOG

본 프로젝트의 주요 변경사항을 기록한다. 포맷은 [Keep a Changelog](https://keepachangelog.com/) 를 따른다.

## [Unreleased]

## [2026-05-22]
### Added
- 문서 하네스 4축 구조 정립 (PRODUCT_SPEC / FEATURES / DATA_MODEL / AI_RULES) + CLAUDE.md 라우팅 허브
- `CHANGELOG.md` 도입 (팀 공유)
- DoD 명문화 (FEATURES.md "완성 정의" 섹션)
```

**갱신 정책:** AI_RULES 및 FEATURES 의 DoD 와 연동. CLAUDE.md 체크리스트가 강제.

---

### 4.3 `docs/PRODUCT_SPEC.md` (신규)

**역할:** 제품 북극성. 모든 의사결정의 상위 컨텍스트.

**섹션:**

1. **한 줄 정의** — 몽글마을이 무엇인지 1문장.
2. **비전·핵심 가치** — 왜 만드는지 3~5줄.
3. **타겟 사용자** — 누구를 위한 것인지.
4. **핵심 사용자 여정** — 회원가입 → 캐릭터 생성 → TODO/플랜 등록 → 퀘스트 분배 → 완료 → 피드 생성 → 댓글·답글 → 회고 (텍스트 시퀀스 또는 mermaid `journey`).
5. **피처 인벤토리** — 4개 피처(+ 인증/토큰/알림 등 인프라) 각 1줄 요약 + `FEATURES.md` 링크.
6. **스코프·비목표·Phase 정의** — Phase 1 포함, Phase 2 백로그 (DATA_MODEL §9 와 정합).
7. **용어집** — 캐릭터 / 퀘스트 / 피드 / 사과(토큰) / 이사(캐릭터 삭제) / 회고 등.
8. **관련 문서 인덱스** — FEATURES / DATA_MODEL / AI_RULES / CHANGELOG 링크.

**예상 분량:** 150~250줄. 사실 입력(타겟 사용자 등 일부)은 현 시점 추정으로 작성하되, "확정 필요" 마커를 명시.

---

### 4.4 `docs/FEATURES.md` (신규)

**역할:** 피처 인덱스 + 공통 설계 패턴 + DoD.

**섹션:**

1. **피처 맵 (표)** — 피처명 / 트리거 / 입력 / 출력 / 상세 문서 / 관련 DATA_MODEL 섹션 / 현재 상태(설계됨/구현중/완성).
2. **피처 간 데이터 플로우** — TODO 확정 → 퀘스트 분배 → 퀘스트 완료 → 피드 생성 → 답글 (텍스트 시퀀스 또는 mermaid `sequenceDiagram`).
3. **공통 설계 패턴**
   - I/O 계약 작성 규약 (Pydantic, 입력/출력/중간 산출물 분리)
   - 에이전트 vs 호출자 책임 분리 패턴 (quest_generation, feed_generation 에서 채택 중인 패턴)
   - Validation → 외부 호출 → 빌드 → 영속화 순서
   - 디렉토리 레이아웃 컨벤션 (`agents/{feature}/{pipeline,nodes,schemas,repository,exceptions}.py`)
4. **완성 정의 (Definition of Done)** — 본 설계의 핵심 추가물.
   1. 단위 + 통합 테스트 통과
   2. `docs/features/{feature}/architecture.mmd` 가 as-built 로 갱신됨
   3. `CHANGELOG.md` 에 `### Added` 또는 `### Changed` 항목 추가됨
   4. 해당 피처 `CLAUDE.md` 의 "미결 사항" 섹션이 모두 해소되었거나 별도 이슈로 이관됨
   5. `docs/TODO.md` 에 완료 항목 1줄 기록 (선택, 결정 사항이 있었을 경우)
5. **피처별 1문단 요약** — 각 피처를 3~5줄로 요약 + `docs/features/{feature}/CLAUDE.md` 링크.

**예상 분량:** 200~300줄.

---

### 4.5 `docs/AI_RULES.md` (신규)

**역할:** 런타임 AI(LLM/VLM) 운영 규칙. 모든 에이전트 코드가 준수해야 하는 공통 정책.

**섹션:**

1. **모델 선택 정책** — Haiku(경량 워커) / Sonnet(메인) / Opus(아키텍처) 가이드. LLM vs VLM 사용 기준.
2. **구조화 출력** — 모든 LLM 응답은 Pydantic/JSON 스키마 강제. 파싱 실패 시 재시도 1회 후 5xx.
3. **재시도·타임아웃 표** — 단계별 정책 (Validation 0회 / LLM 2회 / VLM 2회 / 이미지 생성 1회 — 4개 피처 문서 합본).
4. **언어·길이 제약** — 한국어 강제 위치(캡션, 알림 등), 길이 한도(캡션 140자, 플랜 1500자, 멀티턴 입력 600자, 싱글턴 200자).
5. **프롬프트 카탈로그 관리** — 위치 (`src/prompts/{feature}/...` 제안), 버전 관리, 시스템 프롬프트 작성 규약.
6. **컨텍스트 격리 원칙** — 예: 퀘스트 생성 시 TODO 내용 미주입 (구조적 분리, quest_generation §4 C5 일반화).
7. **토큰·비용 정책** — 사용자 토큰(사과) 지급 상한(일 20개), 일일 호출 한도(이미지 3회, 퀘스트 5회).
8. **실패 처리 패턴** — silent skip / 4xx / 5xx / 백오프 큐 위임 선택 기준.
9. **보안** — PII, 사용자 입력 검증(zod/Pydantic), 프롬프트 인젝션 방어 (사용자 입력은 데이터 섹션에 격리).

**예상 분량:** 200~300줄. 각 피처 문서에 흩어져 있는 정책을 합본하되, 피처 문서는 "AI_RULES 의 일반 정책을 따르되, 본 피처 특수 규정은 …" 형식으로 참조.

---

### 4.6 `docs/DATA_MODEL.md` (변경 없음)

현재 341줄, 15 테이블 정의 완성됨. **본 설계에서는 건드리지 않는다.** 단, 라우팅 테이블에서 참조하는 §1~§6 섹션 번호가 현재 파일과 일치하는지만 확인.

---

### 4.7 `docs/TODO.md` (재정의)

**역할 재정의:** 내부 작업·결정 로그 (CHANGELOG 와 분리).

**포맷:**

```markdown
# 작업 로그 (내부)

> 본 파일은 내부 완료 작업·결정 사항을 기록한다. 팀 공유용 변경사항은 `CHANGELOG.md` 를 사용한다.

## 완료
- [x] 2026-05-22 — 문서 하네스 4축 구조 정립 (PRODUCT_SPEC / FEATURES / AI_RULES / DATA_MODEL + CLAUDE.md 라우팅)
- [x] 2026-05-22 — DATA_MODEL.md 15 테이블 정의
- [x] 2026-05-22 — 4개 피처 설계서 작성 (character_generation, todo, quest_generation, feed_generation)
- [x] 2026-05-22 — CHANGELOG.md 도입 + DoD 명문화

## 진행 중
- (없음)
```

**갱신 정책:** 작업 종료 시 1줄 추가. CLAUDE.md 라우팅 테이블에는 포함하지 않음 (능동적으로 로드할 필요 없음).

---

### 4.8 `docs/features/{feature}/CLAUDE.md` × 4 (상단 헤더 부착)

**변경 범위:** 본문은 그대로 두고, 각 파일 최상단에 다음 표준 헤더를 삽입한다.

```markdown
# {피처명}

**관련 문서:**
- 제품 컨텍스트: [../../PRODUCT_SPEC.md](../../PRODUCT_SPEC.md)
- 피처 인덱스·공통 패턴·DoD: [../../FEATURES.md](../../FEATURES.md)
- 공통 AI 규칙: [../../AI_RULES.md](../../AI_RULES.md)
- 데이터 모델: [../../DATA_MODEL.md](../../DATA_MODEL.md) — 관련 섹션 §{N}
- 아키텍처 다이어그램: [./architecture.mmd](./architecture.mmd)

---

(이하 기존 내용 유지)
```

**관련 DATA_MODEL 섹션 매핑:**

| 피처 | DATA_MODEL 섹션 |
|---|---|
| character_generation | §2 (캐릭터), §6.3 (img_gen_logs) |
| todo | §3 (TODO/일정/퀘스트), §3.4 (tags) |
| quest_generation | §2 (캐릭터), §3.2 (quests) |
| feed_generation | §2 (캐릭터), §4 (피드) |

**4개 파일 모두 본문 미수정.**

---

## 5. 작업 절차 (구현 순서)

1. `docs/superpowers/specs/` 디렉토리 생성 → 본 스펙 저장 (현재 단계).
2. `CHANGELOG.md` 신규 생성 (프로젝트 루트).
3. `docs/PRODUCT_SPEC.md` 신규 작성.
4. `docs/AI_RULES.md` 신규 작성 (4개 피처 문서에서 공통 정책 추출).
5. `docs/FEATURES.md` 신규 작성 (피처 맵 + 공통 패턴 + DoD).
6. `docs/TODO.md` 작업 로그 포맷으로 재초기화.
7. `docs/features/{4개}/CLAUDE.md` 상단 헤더 4건 부착.
8. `CLAUDE.md` 라우팅 허브로 재작성 (라인 1~77 교체).
9. 마지막에 `CHANGELOG.md` 와 `docs/TODO.md` 에 본 작업 완료 항목 추가.
10. 글로벌 룰 (`~/.claude/rules/*`) 과 중복되는 부분이 사라졌는지 확인.

---

## 6. 검증 기준 (Acceptance Criteria)

- [ ] `CLAUDE.md` 라우팅 테이블에 9개 행이 모두 존재하고 각 행의 파일 경로가 실재한다.
- [ ] `CHANGELOG.md` 가 Keep a Changelog 포맷이고 `[Unreleased]` 섹션이 존재한다.
- [ ] `docs/PRODUCT_SPEC.md` 의 "피처 인벤토리" 가 4개 피처 모두를 포함하고 각 항목이 `FEATURES.md` 또는 해당 피처 문서로 링크된다.
- [ ] `docs/FEATURES.md` 의 "완성 정의" 섹션이 4개 항목(테스트 / mmd / CHANGELOG / 미결 사항 정리)을 포함한다.
- [ ] `docs/AI_RULES.md` 의 재시도 표가 4개 피처 문서의 정책을 모두 포함한다.
- [ ] `docs/features/{4개}/CLAUDE.md` 각각의 1~10번째 줄 안에 표준 헤더가 존재한다.
- [ ] `docs/TODO.md` 가 작업 로그 포맷이고 본 작업이 완료 항목으로 기록되어 있다.
- [ ] 글로벌 코딩 가이드와 중복되는 텍스트가 프로젝트 `CLAUDE.md` 에 남아있지 않다.
- [ ] DATA_MODEL.md 는 한 줄도 수정되지 않았다.

---

## 7. 위험 및 완화

| 위험 | 완화 |
|---|---|
| 라우팅 테이블이 신규 피처 추가 시 업데이트 누락 | `FEATURES.md` DoD 에 "라우팅 테이블 갱신" 명시 (5번 항목으로 추가 가능) |
| `architecture.mmd` 가 설계 시점에 머물러 as-built 와 괴리 | DoD 2번 강제 + CLAUDE.md 체크리스트 |
| CHANGELOG 와 TODO.md 역할 혼동 | 각 파일 상단에 "팀 공유 vs 내부" 명시 |
| PRODUCT_SPEC 의 "타겟 사용자/비전" 이 추정으로 작성될 위험 | "확정 필요" 마커 표시, 사용자 검토 시 보완 요청 |
| 피처 문서 헤더가 본문과 중복(이미 본문에 "참고" 섹션이 있음) | 헤더는 상위 문서 역참조만, 본문 "참고" 는 외부/주변 문서로 역할 분리 |

---

## 8. 결정·미결 사항

### 결정됨 (사용자 확인)

- FEATURES 구조: **인덱스형** (피처 상세는 `docs/features/{feature}/CLAUDE.md` 유지)
- AI_RULES 범위: **런타임 AI 규칙** (Claude Code 코딩 규칙은 글로벌 위임)
- 라우팅 방식: **조건별 라우팅 테이블** (CLAUDE.md)
- PRODUCT_SPEC 범위: **제품 전체 스키마** (북극성 역할)
- TODO.md: **유지하며 내부 완료 작업 로그로 재정의**
- CHANGELOG.md: **신규 도입, 프로젝트 루트, Keep a Changelog 스타일**
- Mermaid 플로우: **`docs/features/{feature}/architecture.mmd` 를 as-built 로 갱신하는 정책을 DoD 로 명문화**

### 미결 (구현 단계에서 결정)

- `PRODUCT_SPEC.md` 의 "타겟 사용자/비전" 초기 문구 — 사용자 입력 또는 추정 + 검토 표시.
- `AI_RULES.md` 의 프롬프트 카탈로그 경로 — `src/prompts/{feature}/...` 안 vs 별도 위치.
- DoD 5번 항목(라우팅 테이블 갱신)을 명시할지 — 본 스펙에서는 위험 완화책으로만 언급.

---

## 9. 본 설계 이후

본 스펙 승인 후 → `writing-plans` 스킬로 구현 계획서를 작성하고, 그 계획에 따라 단계별로 파일을 생성·교체한다. 구현 종료 시 CHANGELOG/TODO 에 본 작업 완료 항목을 추가한다.
