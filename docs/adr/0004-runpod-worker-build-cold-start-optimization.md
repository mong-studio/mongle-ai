# ADR-0004: RunPod 워커 빌드·콜드스타트 최적화 (레이어 순서·revision 핀·429 백오프)

**Date**: 2026-06-21
**Status**: accepted
**Deciders**: 개발팀

## Context

RunPod Serverless LLM·이미지 워커의 콜드스타트가 수 분 걸려 서버→RunPod 요청이 타임아웃되는 문제가 있었다. 분석 결과 지연은 추론이 아니라 워밍/콜드스타트였고(hot LLM 8토큰 0.25초, 실제 워크로드 ~40초), 콜드스타트의 핵심은 가중치 로드다. 가중치는 Dockerfile 에서 이미지에 bake 하지만 다음 비효율이 남아 있었다.

1. **image_gen 레이어 순서 역행**: `requirements.txt` 설치가 `bake` 앞에 있어, 의존성 한 줄만 바꿔도 SDXL+ControlNet 수 GB 가 재다운로드된다 → CI 빌드 지연 + HF 429. (llm 워커는 이미 bake→requirements 순서로 회피 중.)
2. **429 백오프 부재(image_gen)**: 더 크고 인기 많은 SDXL 을 받는데 재시도가 없어 CI 빌드가 HF rate limit 으로 깨질 위험. (llm bake 는 백오프 보유.)
3. **모델 revision 미고정**: 의존성은 핀했으나 가중치는 `main` 최신을 받아 모델 repo 업데이트 시 빌드마다 다른 스냅샷이 silently 구워진다(재현성·드리프트). bake 와 런타임이 다른 revision 을 쓰면 런타임 캐시 미스로 재다운로드가 난다.

## Decision

1. **가중치 bake 를 app 의존성보다 앞 레이어로.** image_gen 의 의존성을 ML 스택(`requirements-ml.txt`, bake·런타임 공용)과 app 의존성(`requirements.txt`, runpod SDK)으로 분리하고 순서를 `ML 스택 → bake → app 의존성 → 코드 COPY` 로 둔다. app 의존성을 바꿔도 bake 캐시가 유지되고, ML 스택을 바꿀 때만 재-bake 된다(이때는 호환성 재검증이 필요하므로 의도된 동작).
2. **429 지수 백오프를 image_gen bake 에도 적용**(llm 과 동일 패턴).
3. **모델 가중치를 commit SHA(revision)로 고정**하되 bake 와 런타임 로더 양쪽에 동일하게 적용한다: Qwen2.5-7B-Instruct `a09a354…`, stable-diffusion-xl-base-1.0 `46216598…`, controlnet-canny-sdxl-1.0 `eb115a19…`, lcm-lora-sdxl `a18548dd…`. 우리 소유 LoRA 는 런타임 fetch 를 유지한다(repo 통제 가능).

## Alternatives Considered

### Alternative 1: 네트워크 볼륨에 가중치 적재
- **Pros**: 이미지 슬림, 워커 간 가중치 공유
- **Cons**: 볼륨 리전 잠금, 마운트가 bake 경로를 가려(shadow) 재다운로드 유발(과거 함정)
- **Why not**: bake-in-image 가 이미 동작 중이고 shadow 위험이 큼

### Alternative 2: workersMin=1 상시 워커
- **Pros**: 콜드스타트 자체 제거
- **Cons**: GPU 24/7 과금(엔드포인트 3개 ≈ 월 $900-1000)
- **Why not**: 저트래픽 단계엔 과한 비용. 별도로 idleTimeout=600 으로 완화 중

### Alternative 3: image bake 를 snapshot_download + allow_patterns 로(huggingface_hub 만 필요)
- **Pros**: llm 처럼 ML 스택 없이 bake → 레이어 단순
- **Cons**: fp16 variant 파일 패턴을 빠뜨리면 런타임에 silently 재다운로드
- **Why not**: from_pretrained 가 "런타임과 정확히 같은 파일"을 보장 → 정확성 우선. requirements 분리로 레이어 안정성은 확보

## Consequences

### Positive
- app 의존성 변경 시 SDXL 수 GB 재다운로드 제거 → CI 빌드 단축, 429 위험 감소
- 재현 가능한 빌드(가중치 SHA 고정)
- bake/런타임 revision 일치로 런타임 콜드 재다운로드 차단

### Negative
- image_gen 의존성이 두 파일로 분리되어 관리 포인트 증가
- 모델 업그레이드 시 SHA 를 bake·런타임 양쪽에서 갱신해야 함(불일치 시 재다운로드)

### Risks
- SHA 갱신 누락으로 bake/런타임 불일치 → 콜드 재다운로드. 완화: 두 곳을 같은 PR 에서 갱신하고 SHA 를 본 ADR 에 명시
- ML 스택 변경 시 재-bake 로 빌드가 느려질 수 있으나 빈도 낮음(의도된 동작)
