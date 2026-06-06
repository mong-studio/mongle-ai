# ADR-0001: SFT 데이터셋 messages 포맷 통일 + provenance 다중 소스

**Date**: 2026-06-05
**Status**: accepted
**Deciders**: Junghee Im

## Context

`sft_pipeline/` 는 단기 시험준비 후기만 단일턴(`instruction/input/output`) JSONL 로 생성했다. 그러나 플래너(몽글)는 학습 계획뿐 아니라 일상 계획까지 다루는 멀티턴 어시스턴트라 일상 대화 데이터가 필요해졌다. 시험(단일턴)과 일상(멀티턴), 서로 다른 출처를 하나의 학습 데이터셋에 담아야 한다.

## Decision

SFT 출력 스키마를 `{messages: [{role, content}...], meta}` 로 통일한다. 시험 단일턴은 user→assistant 2턴으로 마이그레이션하고, `meta.provenance`(`exam-crawl` / `daily-latte`) 로 출처를 구분한다. `validate_dataset` 은 messages 스키마를 검증하되 exam-crawl 출처에만 `exam_type`/`result` 를 강제한다(provenance 조건부).

## Alternatives Considered

### Alternative 1: 시험/일상 데이터셋 분리 유지
- **Pros**: 기존 코드 변경 최소.
- **Cons**: 포맷(단일턴 vs 멀티턴) 불일치, 학습 시 병합·정규화 부담.
- **Why not**: 한 모델에 두 능력을 함께 학습시키려면 단일 포맷이 필요.

### Alternative 2: 단일턴 instruction 포맷 유지(일상도 단일턴)
- **Pros**: 기존 build 로직 재사용.
- **Cons**: 멀티턴 대화 능력을 학습시킬 수 없음.
- **Why not**: 일상 계획은 본질적으로 멀티턴(요청→제안→제약→조정)이라 부적합.

## Consequences

### Positive
- 단일턴·멀티턴을 한 스키마로 일관 처리, 트레이너 호환 용이.
- provenance 로 출처별 필터·검증·릴리스 정책 적용 가능([[0002]]).

### Negative
- 기존 `build_sft_dataset`·`validate_dataset`·테스트 마이그레이션 필요(완료, 74 tests 통과).
- validate 가 provenance 조건부 검증으로 다소 복잡해짐.

### Risks
- 트레이너별 messages 키 기대치 차이 → 통일 스키마(role/content)로 표준에 맞춰 완화.
