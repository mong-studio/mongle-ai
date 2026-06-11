# Career Wiki Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code 세션의 트러블슈팅·기술 결정을 Obsidian 커리어 볼트에 누적하는 전역 하네스(스킬 + 커맨드 4개 + Stop 훅 + 볼트 스캐폴드)를 구축한다.

**Architecture:** Karpathy LLM-Wiki 패턴. 볼트에 중립 기록(Decisions)과 이력서 서사(Portfolio)를 분리해 `[[링크]]`로 엮는다. `~/.claude/` 전역에 방법론 스킬 1개 + 얇은 슬래시 커맨드 4개 + 경량 Stop 훅(LLM 미호출, 후보만 `_Inbox/`에 적재)을 둔다.

**Tech Stack:** Markdown + YAML frontmatter (Obsidian), Claude Code 스킬/커맨드/훅, Bash(Stop 훅 스크립트), Python3(설정 병합·테스트 유틸).

**참조 스펙:** `docs/superpowers/specs/2026-06-04-career-wiki-harness-design.md`

---

## File Structure

생성/수정 파일 맵:

**볼트 (`/Users/jpaper/Documents/Obsidian Vault/Career Wiki/`)**
- Create: `00 Schema.md` — 위키 규칙서(LLM이 따르는 CLAUDE.md). 책임: 폴더/타입/템플릿/규약 단일 출처.
- Create: `00 Index.md` — 자동 유지 카탈로그(MOC). 책임: 전체 페이지 색인.
- Create: `Decisions/.gitkeep`, `Portfolio/.gitkeep`, `Projects/.gitkeep`, `Tech/.gitkeep`, `_Inbox/.gitkeep` — 폴더 골격.

**전역 도구 (`~/.claude/`)**
- Create: `skills/career-wiki/SKILL.md` — 방법론·볼트경로·템플릿·4개 워크플로우 단일 출처.
- Create: `commands/wiki-log.md` — 현재 세션 컴파일 진입점.
- Create: `commands/wiki-ingest.md` — 기존 산출물 일괄 수집 진입점.
- Create: `commands/wiki-query.md` — RAG 질의 진입점.
- Create: `commands/wiki-lint.md` — 건강검진 진입점.
- Create: `hooks/wiki-capture.sh` — 세션 종료 후보 적재(경량, LLM 미호출).
- Modify: `settings.json` — `hooks.Stop` 배열에 위 스크립트 등록(기존 항목 보존).

각 파일은 단일 책임을 가진다. 커맨드는 스킬에 위임하는 얇은 래퍼이고, 스킬이 모든 절차 로직을 보유한다. 훅은 캡처만 담당하고 컴파일은 하지 않는다.

---

## Task 1: 볼트 스캐폴드 (폴더 + 색인)

볼트에 `Career Wiki/` 골격과 빈 `00 Index.md`를 만든다. (스키마 본문은 Task 2에서 작성)

**Files:**
- Create: `/Users/jpaper/Documents/Obsidian Vault/Career Wiki/00 Index.md`
- Create: `/Users/jpaper/Documents/Obsidian Vault/Career Wiki/{Decisions,Portfolio,Projects,Tech,_Inbox}/.gitkeep`

- [ ] **Step 1: 폴더 골격 생성**

```bash
VAULT="/Users/jpaper/Documents/Obsidian Vault/Career Wiki"
mkdir -p "$VAULT"/{Decisions,Portfolio,Projects,Tech,_Inbox}
for d in Decisions Portfolio Projects Tech _Inbox; do touch "$VAULT/$d/.gitkeep"; done
```

- [ ] **Step 2: `00 Index.md` 작성**

파일: `/Users/jpaper/Documents/Obsidian Vault/Career Wiki/00 Index.md`

```markdown
---
type: index
updated: 2026-06-04
---

# Career Wiki — Index

> 자동 유지되는 카탈로그. `/wiki-log`·`/wiki-ingest`가 갱신한다. 수동 편집 가능.

## Decisions
<!-- decisions:start -->
_아직 없음_
<!-- decisions:end -->

## Portfolio
<!-- portfolio:start -->
_아직 없음_
<!-- portfolio:end -->

## Projects
<!-- projects:start -->
_아직 없음_
<!-- projects:end -->

## Tech
<!-- tech:start -->
_아직 없음_
<!-- tech:end -->
```

- [ ] **Step 3: 구조 검증**

Run:
```bash
VAULT="/Users/jpaper/Documents/Obsidian Vault/Career Wiki"
find "$VAULT" -type d | sort && test -f "$VAULT/00 Index.md" && echo "INDEX OK"
```
Expected: `Decisions Portfolio Projects Tech _Inbox` 5개 폴더 + `INDEX OK`.

- [ ] **Step 4: Commit (볼트가 git 저장소인 경우에만)**

```bash
VAULT="/Users/jpaper/Documents/Obsidian Vault"
if git -C "$VAULT" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$VAULT" add "Career Wiki/" && git -C "$VAULT" commit -m "feat: career-wiki vault scaffold"
else
  echo "볼트는 git 저장소가 아님 — 커밋 생략"
fi
```
Expected: 커밋 생성 또는 "커밋 생략" 메시지. (볼트 git 여부와 무관하게 진행)

---

## Task 2: 위키 규칙서 `00 Schema.md`

LLM이 위키를 동일 규약으로 다루도록 하는 단일 규칙서. 페이지 템플릿 4종을 포함한다.

**Files:**
- Create: `/Users/jpaper/Documents/Obsidian Vault/Career Wiki/00 Schema.md`

- [ ] **Step 1: `00 Schema.md` 작성**

파일: `/Users/jpaper/Documents/Obsidian Vault/Career Wiki/00 Schema.md`

````markdown
---
type: schema
updated: 2026-06-04
---

# Career Wiki — Schema (규칙서)

이 볼트는 Claude Code 세션의 트러블슈팅·기술 결정을 이력서·포트폴리오용으로 누적한다.
모든 LLM 도구는 페이지를 만들거나 고치기 전에 이 문서를 따른다.

## 폴더 / 타입

| 폴더 | type | 역할 |
|------|------|------|
| `Decisions/` | `decision` \| `troubleshooting` | 중립 사실 기록(진실의 출처) |
| `Portfolio/` | `portfolio` | 이력서용 STAR 서사 |
| `Projects/` | `project` | 프로젝트 엔티티(MOC) |
| `Tech/` | `tech` | 기술·패턴 엔티티 |
| `_Inbox/` | `candidate` | Stop 훅이 떨군 검토 대기 후보 |

## 규약

- 페이지 링크는 `[[kebab-case-slug]]`.
- Decision 파일명: `YYYY-MM-DD-<slug>.md` (시간순). 엔티티: 날짜 없는 `<slug>.md`.
- 태그: `#decision #troubleshooting #portfolio` + 기술 태그.
- **메트릭 날조 금지.** Portfolio의 수치/impact는 evidence(PR·commit·로그)로 뒷받침되는 것만.
- 중립 사실은 Decisions에, 성취 프레이밍은 Portfolio에. 서로 `[[링크]]`로 연결.

## 템플릿 — Decision

```markdown
---
type: decision        # 또는 troubleshooting
date: YYYY-MM-DD
project: "[[<project-slug>]]"
tech: ["[[<tech-slug>]]"]
status: accepted      # proposed | accepted | superseded
tags: [decision]
evidence: []          # PR#, commit, docs/adr/... 경로
portfolio: ""         # "[[<portfolio-slug>]]" (있으면)
---

# <제목>

## Context
<배경 — 왜 이 결정이 필요했나>

## Problem
<해결하려던 문제 / 트러블슈팅이면 증상>

## Options
<검토한 대안들과 트레이드오프>

## Decision
<무엇을 택했나 / 트러블슈팅이면 근본 원인>

## Consequences
<결과·영향·후속>

## Evidence
<PR/commit/ADR/로그 링크>
```

## 템플릿 — Portfolio (STAR)

```markdown
---
type: portfolio
skills: []
impact: ""            # 검증 가능한 것만
role: ""
backed_by: []         # "[[<decision-slug>]]"
tags: [portfolio]
---

# <제목>

## Situation
## Task
## Action
## Result

## Resume bullet
- <한 줄 이력서 불릿>
```

## 템플릿 — Project

```markdown
---
type: project
stack: []
role: ""
tags: [project]
---

# <프로젝트명>

## 개요
## 내 역할
## 스택
## 핵심 결정
<!-- [[decision-slug]] 링크들 -->
## 포트폴리오
<!-- [[portfolio-slug]] 링크들 -->
```

## 템플릿 — Tech

```markdown
---
type: tech
tags: [tech]
---

# <기술/패턴명>

## 정의
## 사용처
<!-- [[decision-slug]] / [[project-slug]] 링크들 -->
## 배운 점 / 함정
```

## Index 갱신 규약

`00 Index.md`의 `<!-- <section>:start -->`~`<!-- <section>:end -->` 마커 사이에
`- [[slug]] — 한 줄 요약` 항목을 알파벳/시간순으로 유지한다.
````

- [ ] **Step 2: 템플릿 4종 존재 검증**

Run:
```bash
F="/Users/jpaper/Documents/Obsidian Vault/Career Wiki/00 Schema.md"
grep -c "## 템플릿" "$F"
```
Expected: `4`

- [ ] **Step 3: Commit (볼트가 git인 경우)**

```bash
VAULT="/Users/jpaper/Documents/Obsidian Vault"
git -C "$VAULT" rev-parse --git-dir >/dev/null 2>&1 && git -C "$VAULT" add "Career Wiki/00 Schema.md" && git -C "$VAULT" commit -m "feat: career-wiki schema doc" || echo "git 저장소 아님 — 생략"
```
Expected: 커밋 또는 생략 메시지.

---

## Task 3: 스킬 `career-wiki`

방법론·볼트 경로·4개 연산 워크플로우를 담는 단일 스킬. 커맨드들이 이 스킬에 위임한다.

**Files:**
- Create: `~/.claude/skills/career-wiki/SKILL.md`

- [ ] **Step 1: `SKILL.md` 작성**

파일: `/Users/jpaper/.claude/skills/career-wiki/SKILL.md`

````markdown
---
name: career-wiki
description: Claude Code 세션의 트러블슈팅·기술 결정을 Obsidian 커리어 볼트(이력서·포트폴리오용)에 누적·질의한다. "위키에 정리", "wiki-log", "wiki-ingest", "wiki-query", "wiki-lint", 결정/트러블슈팅을 기록하자는 요청에 사용.
---

# Career Wiki

Karpathy LLM-Wiki 패턴으로 커리어 지식을 누적하는 하네스.

**볼트 루트:** `/Users/jpaper/Documents/Obsidian Vault/Career Wiki`
**규칙서:** 작업 전 항상 `<볼트>/00 Schema.md`를 먼저 읽고 그 템플릿·규약을 따른다.

## 공통 컴파일 파이프라인 (log·ingest 공유)

1. 원본(현재 세션 대화 / 주어진 소스)에서 **결정·트러블슈팅**의 핵심을 추출한다.
2. 같은 결정의 기존 Decision 페이지가 있는지 `Decisions/`를 검색한다(중복 방지).
3. 없으면 Schema의 Decision 템플릿으로 `Decisions/YYYY-MM-DD-<slug>.md`를 **중립 사실**로 작성한다.
4. 이력서 가치가 있으면 Portfolio 템플릿으로 STAR 페이지를 만들거나 갱신하고, Decision의 frontmatter `portfolio`와 Portfolio의 `backed_by`를 서로 `[[링크]]`한다.
5. 관련 `Projects/<slug>.md`·`Tech/<slug>.md` 엔티티를 만들거나 "핵심 결정/사용처"에 `[[역링크]]`를 추가한다.
6. `00 Index.md`의 해당 섹션 마커 사이에 `- [[slug]] — 요약`을 추가한다.
7. 끝에 lint(아래)를 가볍게 돌려 깨진 링크가 없는지 확인한다.

**원칙:** 사실은 Decisions, 서사는 Portfolio. 메트릭 날조 금지. 외과적 — 요청된 결정만 기록.

## 연산

### log (현재 세션)
지금 대화에서 내려진 결정/트러블슈팅을 위 파이프라인으로 컴파일한다.
어떤 결정을 기록할지 모호하면 후보를 나열하고 사용자에게 확인한다.

### ingest <소스>
주어진 소스를 원본으로 같은 파이프라인을 돈다. 소스 해석:
- 경로(`docs/adr`, 파일): 해당 파일들을 읽어 각 ADR/문서를 Decision으로.
- `PR#<n>` 또는 PR URL: `gh pr view <n>`로 본문·diff 요약을 읽어 Decision으로.
- "session summary": 현재 세션 요약을 원본으로.
여러 항목이면 항목당 Decision 1개, 중복은 기존 페이지에 병합.

### query <질문>
1. `00 Index.md`와 frontmatter `tags`로 후보 페이지를 좁힌다.
2. 후보 페이지 본문을 읽고 `[[링크]]`를 따라 인접 페이지로 확장한다(벡터 없이 키워드+그래프).
3. **인용(페이지명)** 을 붙여 답을 합성한다. 근거가 없으면 "위키에 없음"이라고 말한다.

### lint
볼트를 점검해 보고한다(자동 수정하지 않고 제안):
- 고아 페이지(아무도 링크 안 함), 깨진 `[[링크]]`(대상 파일 없음).
- 오래된/모순 주장, Portfolio의 evidence 없는 메트릭.
- `00 Index.md`에 누락된 페이지.

## Stop 훅 후보 처리
`_Inbox/`의 후보 파일은 자동 편입하지 않는다. 사용자가 검토를 요청하면 후보를 읽고
log 파이프라인으로 승격한 뒤 후보 파일을 지운다.
````

- [ ] **Step 2: 스킬 인식 검증**

Run:
```bash
test -f ~/.claude/skills/career-wiki/SKILL.md && grep -q "Career Wiki" ~/.claude/skills/career-wiki/SKILL.md && echo "SKILL OK"
```
Expected: `SKILL OK`

- [ ] **Step 3: Commit (전역 `~/.claude`가 git인 경우)**

```bash
git -C ~/.claude rev-parse --git-dir >/dev/null 2>&1 && git -C ~/.claude add skills/career-wiki/SKILL.md && git -C ~/.claude commit -m "feat: career-wiki skill" || echo "~/.claude git 아님 — 생략"
```
Expected: 커밋 또는 생략.

---

## Task 4: 슬래시 커맨드 4개

스킬에 위임하는 얇은 진입점. 각 커맨드는 `career-wiki` 스킬을 호출하고 해당 연산을 지정한다.

**Files:**
- Create: `~/.claude/commands/wiki-log.md`
- Create: `~/.claude/commands/wiki-ingest.md`
- Create: `~/.claude/commands/wiki-query.md`
- Create: `~/.claude/commands/wiki-lint.md`

- [ ] **Step 1: `wiki-log.md` 작성**

파일: `/Users/jpaper/.claude/commands/wiki-log.md`

```markdown
---
description: 현재 세션의 결정·트러블슈팅을 커리어 위키에 컴파일
---

career-wiki 스킬을 사용해 **log** 연산을 수행한다.
지금 이 세션 대화에서 내려진 기술 결정·트러블슈팅을 추출해
`00 Schema.md` 규약대로 Decision/Portfolio/엔티티/Index를 작성·갱신하라.
기록할 결정이 모호하면 후보를 나열하고 확인을 받아라.
```

- [ ] **Step 2: `wiki-ingest.md` 작성**

파일: `/Users/jpaper/.claude/commands/wiki-ingest.md`

```markdown
---
description: 기존 산출물(ADR·PR·세션요약)을 커리어 위키로 일괄 수집
argument-hint: <소스 경로 | PR#번호 | "session summary">
---

career-wiki 스킬을 사용해 **ingest** 연산을 수행한다.
소스: $ARGUMENTS
해당 소스를 읽어 항목당 Decision 페이지로 컴파일하고, 중복은 기존 페이지에 병합하며,
엔티티·Index를 갱신하라. 소스가 비었으면 `docs/adr`를 기본 소스로 제안하라.
```

- [ ] **Step 3: `wiki-query.md` 작성**

파일: `/Users/jpaper/.claude/commands/wiki-query.md`

```markdown
---
description: 커리어 위키에 RAG처럼 질의(인용 포함 답변)
argument-hint: <질문>
---

career-wiki 스킬을 사용해 **query** 연산을 수행한다.
질문: $ARGUMENTS
Index와 태그로 후보를 좁히고 `[[링크]]`를 따라 확장한 뒤,
페이지명을 인용해 답을 합성하라. 근거가 없으면 "위키에 없음"이라고 답하라.
```

- [ ] **Step 4: `wiki-lint.md` 작성**

파일: `/Users/jpaper/.claude/commands/wiki-lint.md`

```markdown
---
description: 커리어 위키 건강검진(고아·깨진 링크·모순·메트릭)
---

career-wiki 스킬을 사용해 **lint** 연산을 수행한다.
볼트를 점검해 고아 페이지, 깨진 `[[링크]]`, 모순/오래된 주장,
evidence 없는 Portfolio 메트릭, Index 누락을 보고하라(자동 수정 말고 제안).
```

- [ ] **Step 5: 4개 커맨드 존재 검증**

Run:
```bash
ls ~/.claude/commands/wiki-log.md ~/.claude/commands/wiki-ingest.md ~/.claude/commands/wiki-query.md ~/.claude/commands/wiki-lint.md && echo "CMDS OK"
```
Expected: 4개 파일 경로 + `CMDS OK`.

- [ ] **Step 6: Commit (전역 git인 경우)**

```bash
git -C ~/.claude rev-parse --git-dir >/dev/null 2>&1 && git -C ~/.claude add commands/wiki-log.md commands/wiki-ingest.md commands/wiki-query.md commands/wiki-lint.md && git -C ~/.claude commit -m "feat: career-wiki slash commands" || echo "~/.claude git 아님 — 생략"
```
Expected: 커밋 또는 생략.

---

## Task 5: Stop 훅 (경량 후보 캡처)

세션 종료 시 결정 신호가 있으면 `_Inbox/`에 후보 스텁을 적재한다. LLM 미호출. 토글 가능.

Stop 훅은 stdin으로 JSON(`transcript_path`, `cwd`, `session_id` 등)을 받는다.
스크립트는 트랜스크립트를 결정 키워드로 grep해 신호가 있을 때만 후보를 쓴다.
`~/.claude/wiki-capture.disabled` 파일이 있으면 즉시 종료(토글).

**Files:**
- Create: `~/.claude/hooks/wiki-capture.sh`
- Test: `~/.claude/hooks/test_wiki_capture.sh`
- Modify: `~/.claude/settings.json` (`hooks.Stop` 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

파일: `/Users/jpaper/.claude/hooks/test_wiki_capture.sh`

```bash
#!/usr/bin/env bash
# wiki-capture.sh 동작 테스트. 임시 트랜스크립트로 입력을 위조한다.
set -u
HOOK="$(dirname "$0")/wiki-capture.sh"
VAULT="/Users/jpaper/Documents/Obsidian Vault/Career Wiki/_Inbox"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail=0

# 케이스 1: 결정 키워드 있음 → 후보 생성
TRANSCRIPT="$TMP/t1.jsonl"
printf '%s\n' '{"role":"user","content":"FastAPI를 상태 비저장으로 결정했다 근본 원인은 배포"}' > "$TRANSCRIPT"
before=$(ls "$VAULT" 2>/dev/null | wc -l)
echo "{\"transcript_path\":\"$TRANSCRIPT\",\"cwd\":\"$TMP\",\"session_id\":\"test1\"}" | bash "$HOOK"
after=$(ls "$VAULT" 2>/dev/null | wc -l)
if [ "$after" -gt "$before" ]; then echo "PASS: 후보 생성"; else echo "FAIL: 후보 미생성"; fail=1; fi

# 케이스 2: 키워드 없음 → 후보 미생성
TRANSCRIPT2="$TMP/t2.jsonl"
printf '%s\n' '{"role":"user","content":"안녕 오늘 날씨 좋네"}' > "$TRANSCRIPT2"
before2=$(ls "$VAULT" 2>/dev/null | wc -l)
echo "{\"transcript_path\":\"$TRANSCRIPT2\",\"cwd\":\"$TMP\",\"session_id\":\"test2\"}" | bash "$HOOK"
after2=$(ls "$VAULT" 2>/dev/null | wc -l)
if [ "$after2" -eq "$before2" ]; then echo "PASS: 무신호 무생성"; else echo "FAIL: 불필요 생성"; fail=1; fi

# 케이스 3: 토글 비활성화 → 미생성
touch "$HOME/.claude/wiki-capture.disabled"
before3=$(ls "$VAULT" 2>/dev/null | wc -l)
echo "{\"transcript_path\":\"$TRANSCRIPT\",\"cwd\":\"$TMP\",\"session_id\":\"test3\"}" | bash "$HOOK"
after3=$(ls "$VAULT" 2>/dev/null | wc -l)
rm -f "$HOME/.claude/wiki-capture.disabled"
if [ "$after3" -eq "$before3" ]; then echo "PASS: 토글 동작"; else echo "FAIL: 토글 무시"; fail=1; fi

exit $fail
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `bash ~/.claude/hooks/test_wiki_capture.sh`
Expected: FAIL (스크립트 `wiki-capture.sh` 없음 → 케이스 1 "후보 미생성").

- [ ] **Step 3: 훅 스크립트 구현**

파일: `/Users/jpaper/.claude/hooks/wiki-capture.sh`

```bash
#!/usr/bin/env bash
# Career Wiki — Stop 훅. 결정 신호가 있으면 _Inbox/에 후보 스텁 적재. LLM 미호출.
set -u

# 토글: 비활성화 파일 있으면 종료
[ -f "$HOME/.claude/wiki-capture.disabled" ] && exit 0

INBOX="/Users/jpaper/Documents/Obsidian Vault/Career Wiki/_Inbox"
[ -d "$INBOX" ] || exit 0   # 볼트 미설치면 조용히 종료

# stdin JSON에서 필드 추출 (python3로 안전 파싱)
PAYLOAD="$(cat)"
read -r TRANSCRIPT CWD SID <<EOF
$(printf '%s' "$PAYLOAD" | python3 -c 'import sys,json
d=json.load(sys.stdin)
print(d.get("transcript_path",""), d.get("cwd",""), d.get("session_id","")[:8])' 2>/dev/null)
EOF

[ -n "${TRANSCRIPT:-}" ] && [ -f "$TRANSCRIPT" ] || exit 0

# 결정/트러블슈팅 신호 키워드 카운트
KEYWORDS='결정|트러블|근본 원인|root cause|decision|troubleshoot|trade-?off|왜냐|선택했|채택|버그|회귀|regression|ADR'
HITS=$(grep -aiE "$KEYWORDS" "$TRANSCRIPT" 2>/dev/null | wc -l | tr -d ' ')
[ "${HITS:-0}" -ge 1 ] || exit 0   # 신호 없으면 종료

# 날짜 prefix (LLM/외부 의존 없이 date 사용)
DAY=$(date +%Y-%m-%d)
TS=$(date +%H:%M)
OUT="$INBOX/$DAY-session-candidates.md"
PROJECT=$(basename "${CWD:-unknown}")
BRANCH=$(git -C "${CWD:-.}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "-")
FILES=$(git -C "${CWD:-.}" status --porcelain 2>/dev/null | head -20)

# 후보 파일이 없으면 헤더 생성
if [ ! -f "$OUT" ]; then
  {
    echo "---"
    echo "type: candidate"
    echo "date: $DAY"
    echo "tags: [candidate]"
    echo "---"
    echo
    echo "# 검토 대기 후보 — $DAY"
    echo
    echo "> Stop 훅 자동 적재. \`/wiki-log\`로 검토·승격 후 항목을 지운다. 자동 편입 아님."
    echo
  } >> "$OUT"
fi

# 세션 항목 추가(append-only)
{
  echo "## $TS · $PROJECT ($BRANCH) · 신호 ${HITS}건"
  echo "- session: \`${SID:-?}\`"
  echo "- transcript: \`$TRANSCRIPT\`"
  if [ -n "$FILES" ]; then
    echo "- 변경 파일:"
    echo "$FILES" | sed 's/^/  - `/; s/$/`/'
  fi
  echo "- [ ] 승격 완료?"
  echo
} >> "$OUT"

exit 0
```

- [ ] **Step 4: 실행 권한 부여 후 테스트 → 통과 확인**

Run:
```bash
chmod +x ~/.claude/hooks/wiki-capture.sh ~/.claude/hooks/test_wiki_capture.sh
bash ~/.claude/hooks/test_wiki_capture.sh; echo "exit=$?"
rm -f "/Users/jpaper/Documents/Obsidian Vault/Career Wiki/_Inbox/$(date +%Y-%m-%d)-session-candidates.md"
```
Expected: 3개 `PASS` + `exit=0`. (마지막 줄이 테스트가 만든 후보 파일을 정리)

- [ ] **Step 5: `settings.json`에 Stop 훅 등록 (기존 보존)**

Run (python3로 안전 병합 — 기존 키 보존):
```bash
python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.claude/settings.json")
d = json.load(open(p))
hooks = d.setdefault("hooks", {})
stop = hooks.setdefault("Stop", [])
cmd = os.path.expanduser("~/.claude/hooks/wiki-capture.sh")
already = any(
    h.get("command") == cmd
    for entry in stop for h in entry.get("hooks", [])
)
if not already:
    stop.append({"hooks": [{"type": "command", "command": cmd}]})
    json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
    print("ADDED Stop hook")
else:
    print("ALREADY present")
PY
```
Expected: `ADDED Stop hook`. (settings.json의 다른 키는 그대로)

- [ ] **Step 6: 등록 검증**

Run:
```bash
python3 -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude/settings.json'))); print('OK' if any('wiki-capture.sh' in h.get('command','') for e in d['hooks']['Stop'] for h in e['hooks']) else 'MISSING')"
```
Expected: `OK`

- [ ] **Step 7: Commit (전역 git인 경우)**

```bash
git -C ~/.claude rev-parse --git-dir >/dev/null 2>&1 && git -C ~/.claude add hooks/wiki-capture.sh hooks/test_wiki_capture.sh settings.json && git -C ~/.claude commit -m "feat: career-wiki Stop hook capture" || echo "~/.claude git 아님 — 생략"
```
Expected: 커밋 또는 생략.

---

## Task 6: 엔드투엔드 검증 (성공 기준 6항)

실제 데이터로 하네스를 한 바퀴 돌려 스펙 §6 성공 기준을 확인한다. 이 태스크는 Claude가 스킬/커맨드를 **대화로** 실행하는 검증이다(스크립트 아님).

**Files:** (이 태스크는 위키 콘텐츠를 생성한다 — 산출물은 볼트 내부)

- [ ] **Step 1: ADR 일괄 수집**

`/wiki-ingest docs/adr` 실행.
Expected: `Decisions/`에 ADR 0001~0005 대응 페이지 5개 생성, 각 frontmatter에 `evidence: [docs/adr/...]`, `Projects/mongle-ai.md` 생성·연결, `00 Index.md` Decisions 섹션 갱신.

검증:
```bash
ls "/Users/jpaper/Documents/Obsidian Vault/Career Wiki/Decisions" | grep -c '\.md$'   # >=5 기대
grep -q "mongle-ai" "/Users/jpaper/Documents/Obsidian Vault/Career Wiki/00 Index.md" && echo "INDEX OK"
```

- [ ] **Step 2: 현재 세션 로그**

`/wiki-log` 실행 (이 career-wiki 구축 결정을 기록).
Expected: 새 Decision 1개 + 이력서 가치 있으면 Portfolio STAR 1개 + `Tech/`에 관련 엔티티(`obsidian`, `claude-code-hooks` 등) + 상호 `[[링크]]`.

검증:
```bash
grep -rl "backed_by" "/Users/jpaper/Documents/Obsidian Vault/Career Wiki/Portfolio" | head -1 && echo "PORTFOLIO OK"
```

- [ ] **Step 3: 질의**

`/wiki-query "FastAPI를 왜 상태 비저장으로 했나?"` 실행.
Expected: ADR 0001 대응 Decision 페이지를 **인용**한 답변. 근거 없으면 "위키에 없음".

- [ ] **Step 4: 린트**

`/wiki-lint` 실행.
Expected: 고아/깨진 링크 0 보고, 또는 발견 항목을 정확히 나열. 깨진 링크가 있으면 Step 1~2의 링크를 수정 후 재실행.

- [ ] **Step 5: Stop 훅 실연**

Run (훅을 수동 트리거해 후보 생성 확인):
```bash
T=$(mktemp); printf '%s\n' '{"role":"user","content":"이 결정을 채택했다 근본 원인 분석"}' > "$T"
echo "{\"transcript_path\":\"$T\",\"cwd\":\"$PWD\",\"session_id\":\"e2e-check\"}" | bash ~/.claude/hooks/wiki-capture.sh
ls "/Users/jpaper/Documents/Obsidian Vault/Career Wiki/_Inbox/"*.md && echo "INBOX OK"; rm -f "$T"
```
Expected: `_Inbox/`에 후보 파일 + `INBOX OK`.

- [ ] **Step 6: Obsidian 그래프 확인 (수동)**

Obsidian을 열어 그래프 뷰에서 Decisions↔Portfolio↔Projects↔Tech 연결을 눈으로 확인한다.
Expected: 페이지들이 `[[링크]]`로 연결된 그래프.

- [ ] **Step 7: 볼트 콘텐츠 Commit (볼트 git인 경우)**

```bash
VAULT="/Users/jpaper/Documents/Obsidian Vault"
git -C "$VAULT" rev-parse --git-dir >/dev/null 2>&1 && git -C "$VAULT" add "Career Wiki/" && git -C "$VAULT" commit -m "feat: seed career-wiki with mongle-ai decisions" || echo "git 아님 — 생략"
```
Expected: 커밋 또는 생략.

---

## 마무리

- 스펙 §6 성공 기준 6항이 Task 6에서 모두 검증된다.
- 전역 도구(`~/.claude/`)와 볼트(`Obsidian Vault/`)만 변경하며 mongle-ai 레포에는 스펙·플랜 문서만 남는다.
- 후속(YAGNI 제외 항목): 벡터 임베딩, 이력서 PDF 자동 생성 — 본 계획 범위 밖.
