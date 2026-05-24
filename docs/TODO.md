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
