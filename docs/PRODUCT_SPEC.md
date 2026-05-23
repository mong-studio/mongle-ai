# PRODUCT_SPEC

> **몽글마을 (Monggeul Village) — 제품 전체 스키마**
>
> 본 문서는 제품의 북극성이다. 모든 의사결정은 본 문서와 정합해야 한다.
> 세부 문서: [FEATURES.md](./FEATURES.md) · [DATA_MODEL.md](./DATA_MODEL.md) · [AI_RULES.md](./AI_RULES.md) · [CHANGELOG.md](../CHANGELOG.md)

---

## 1. 한 줄 정의

> ⚠ **확정 필요** — 사용자 검토 시 보완.
>
> (초안) 사용자가 직접 만든 AI 캐릭터들이 사는 마을에서 일상의 TODO·일정을 함께 수행하며 작은 성취감을 쌓는 라이프스타일 앱.

## 2. 비전·핵심 가치

> ⚠ **확정 필요** — 초안.

- 사용자의 일상에 캐릭터를 매개로 한 정서적 동기부여를 제공한다.
- 추상적인 "할 일"을 캐릭터의 퀘스트·피드 같은 구체적 형태로 변환해 지속 가능한 자기관리 루틴을 만든다.
- 데이터(태그·회고)를 통해 사용자가 자신의 패턴을 인식하도록 돕는다.

## 3. 타겟 사용자

> ⚠ **확정 필요** — 초안.

- 20~30대 1인 가구·학생·직장인
- 기존 TODO 앱이 무미건조해 지속하지 못한 경험이 있는 사용자
- 캐릭터·게이미피케이션·SNS 요소에 친화적인 사용자

## 4. 핵심 사용자 여정

1. **회원가입·로그인** — 이메일 또는 카카오 소셜 로그인 (`DATA_MODEL.md` §1)
2. **캐릭터 생성** — 페르소나·키워드·이미지로 8bit 픽셀 캐릭터 생성 (계정당 최대 10명, 일 3회 재생성)
3. **TODO/플랜 등록** — 싱글턴(즉시 분할) 또는 멀티턴(챗봇) 모드
4. **퀘스트 분배** — 당일 TODO 확정 시 랜덤 캐릭터에 퀘스트 1:1 분배 (일 5회 한도)
5. **TODO·퀘스트 완료** — 사용자가 TODO 완료 → 토큰(사과) 지급
6. **피드 생성** — 퀘스트 완료 시 캐릭터가 수행 장면 이미지 + 캡션을 피드에 게시
7. **댓글·답글** — 사용자 댓글 → 10분 후 캐릭터 자동 답글
8. **회고** — 일일 회고 작성 (`잘한 점` / `못한 점`)

자세한 피처 간 데이터 플로우: [FEATURES.md §피처 간 데이터 플로우](./FEATURES.md)

## 5. 피처 인벤토리

| 피처 | 1줄 요약 | 상세 |
|---|---|---|
| character_generation | 텍스트·이미지 입력 → 8bit 픽셀 캐릭터·페르소나·말투 생성 | [features/character_generation/CLAUDE.md](./features/character_generation/CLAUDE.md) |
| todo | 자연어 입력으로 TODO·캘린더 일정 생성 (싱글턴/멀티턴) | [features/todo/CLAUDE.md](./features/todo/CLAUDE.md) |
| quest_generation | 당일 TODO에 캐릭터 1:1 분배 + 페르소나 기반 퀘스트 텍스트 생성 | [features/quest_generation/CLAUDE.md](./features/quest_generation/CLAUDE.md) |
| feed_generation | 퀘스트 수행 장면 이미지 + 한글 140자 캡션 생성 | [features/feed_generation/CLAUDE.md](./features/feed_generation/CLAUDE.md) |
| 인증·소셜 로그인 | 이메일·카카오, 자동 로그인(2주) | `DATA_MODEL.md` §1 |
| 토큰(사과) 경제 | TODO 완료·회고 지급, 댓글·커스터마이즈 소모 (일 20개 상한) | `DATA_MODEL.md` §6.1 |
| 알림 | 인앱 알림 (FEED_NEW / QUEST_DEADLINE / RETROSPECT 등) | `DATA_MODEL.md` §6.2 |
| 회고 | 일일 1회 잘한 점·못한 점 기록 | `DATA_MODEL.md` §5 |

## 6. 스코프·비목표·Phase

### Phase 1 (현재)

- 위 피처 인벤토리의 8개 항목
- 단일 플랫폼(모바일/웹은 확정 필요)
- 결제·구독 없음 (토큰은 행동 보상으로만 획득)

### Phase 2 백로그

`DATA_MODEL.md` §9 와 정합. 추후 확장:

- 챗봇 대화 로그 영속화 (멀티턴 컨텍스트)
- 사용자 설정 테이블 (캘린더 온/오프, 포모도로, 디스코드 알림)
- 집 커스터마이징 (외형 이력)

### 비목표

- 캐릭터 간 직접 상호작용(다른 사용자 캐릭터와 친구 등) — Phase 1 범위 밖
- 외부 캘린더 연동(Google Calendar 등) — Phase 1 범위 밖
- 실시간 채팅·멀티플레이 — 영구 비목표

## 7. 용어집

| 용어 | 정의 |
|---|---|
| 캐릭터 | 사용자가 생성한 8bit 픽셀 정면 캐릭터. 페르소나·말투·외형 키워드를 가진다. |
| 마을 | 한 사용자의 캐릭터 컬렉션(최대 10명)이 모인 공간. |
| 이사 | 캐릭터를 활성 해제(`characters.is_active = 0`)하는 행위. 미완료 퀘스트는 다른 캐릭터로 재할당. |
| 퀘스트 | 캐릭터에게 분배된 페르소나 기반 미션 텍스트. **TODO 내용과 무관**(구조적 분리). |
| 피드 | 캐릭터가 퀘스트 완료 시 게시하는 이미지+캡션 게시물 (140자 한글). |
| 사과 (토큰) | 행동 보상으로 획득·소모되는 인앱 토큰. |
| 회고 | 일일 1회 작성하는 잘한 점·못한 점 기록. |

## 8. 관련 문서 인덱스

- 라우팅 허브: [`../CLAUDE.md`](../CLAUDE.md)
- 피처 인덱스·DoD: [`./FEATURES.md`](./FEATURES.md)
- DB 스키마: [`./DATA_MODEL.md`](./DATA_MODEL.md)
- 런타임 AI 규칙: [`./AI_RULES.md`](./AI_RULES.md)
- 팀 공유 변경 로그: [`../CHANGELOG.md`](../CHANGELOG.md)
- 내부 작업 로그: [`./TODO.md`](./TODO.md)
- 피처 상세: `./features/{character_generation,todo,quest_generation,feed_generation}/CLAUDE.md`
