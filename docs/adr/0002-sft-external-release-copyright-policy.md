# ADR-0002: SFT 외부 배포 저작권 정책 + 로컬 오픈모델 합성

**Date**: 2026-06-05
**Status**: accepted
**Deciders**: Junghee Im

## Context

SFT 데이터셋을 외부에 공개·배포할 계획이다. 두 소스의 법적 성격이 다르다: 시험-크롤 데이터는 라이선스 없는 한국 블로그 기반(저작권 보호 대상이며 `evidence_spans` 가 원문 ≤200자 직접 인용)이고, 일상 데이터(MS-LaTTE)는 MIT 다. 또한 상용 LLM(OpenAI/Anthropic)으로 합성한 출력은 ToS 상 재배포·경쟁모델 학습 제약이 있다.

## Decision

`provenance` 기반 release 정책을 둔다. `mix_dataset --release public` 은 외부 공개용으로 `daily-latte`(MIT)만 포함하고 시험-크롤은 제외하며, `--release internal` 은 전체를 내부 학습용으로 포함한다. 멀티턴 합성은 OpenAI 호환 `base_url` 로 **로컬 오픈모델**(예: Qwen, Apache-2.0)을 사용하고(provider-pluggable), 모델이 없으면 결정론적 템플릿으로 폴백한다.

## Alternatives Considered

### Alternative 1: 시험 데이터를 비저작권화 후 공개
- **Pros**: 시험 도메인도 공개 데이터셋에 포함.
- **Cons**: evidence_spans 제거·합성 재작성 비용, 파생물의 잔여 저작권 위험.
- **Why not**: 내부 전용으로 두는 편이 법적으로 명확하고 안전.

### Alternative 2: 상용 API(OpenAI/Anthropic)로 합성
- **Pros**: 즉시 사용, 한국어 품질 높음.
- **Cons**: 출력물 재배포·경쟁모델 학습에 ToS 제약.
- **Why not**: 외부 공개 데이터셋에는 라이선스가 깨끗한 로컬 오픈모델이 안전.

## Consequences

### Positive
- 저작권/ToS 위험을 출처 단위로 격리(공개판은 MIT 데이터만).
- 합성이 기존 OpenAI SDK 의 `base_url` 교체만으로 로컬 모델 사용 → 추가 의존성 0.

### Negative
- 실제 1000+ 멀티턴 합성에 로컬 모델 서버(Ollama/vLLM) 구동이 필요.

### Risks
- release 필터가 블랙리스트(fail-open)면 provenance 누락/오타 시 시험 데이터가 공개판에 새어 들어갈 수 있음 → 화이트리스트(fail-closed, `daily-latte` 만 허용)로 강화 권장(코드 리뷰 [M1]).
