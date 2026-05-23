# character_creation — 결정 사항 로그

본 파일은 캐릭터 생성 에이전트 구현 시 내린 코드 결정사항을 영구 기록한다.

## 2026-05-22 — 초기 구현

1. **포트 분리** — 외부 의존(LLM/VLM/S3/Image Generator/Counter/Repository)을 모두 Protocol 로 추상화. 실제 어댑터는 후속 PR.
2. **에이전트 순수성** — `pipeline.run` 은 DB 저장을 수행하지 않고 `CharacterEntity` 만 반환한다 (`docs/FEATURES.md` §3.2 책임 분리). 저장은 호출자가 `ports.repository.save(entity)` 로 수행.
3. **이미지 생성 실패 시 cleanup** — 원본 업로드가 성공한 뒤 이미지 생성/생성이미지 업로드가 실패하면 파이프라인이 `repository.delete_image_keys([source_key])` 를 호출하여 고아 파일을 막는다. DB 저장 자체 실패에 대한 cleanup 은 호출자 책임.
4. **degrade-on-fail (VLM)** — `docs/features/character_generation/CLAUDE.md` §8 #3 결정에 따라 VLM 재시도 소진 시 None 반환, 파이프라인은 `fallback_persona` 로 이미지 생성을 계속한다.
5. **재시도 회수** — 피처 문서 `docs/features/character_generation/CLAUDE.md` §6 의 강화된 표를 따른다. LLM=3, VLM=3, S3=4, ImageGen=2. (글로벌 `AI_RULES.md` §3 의 LLM=2/VLM=2/S3=3/ImageGen=1 보다 1회씩 추가. 사유: 본 피처는 외부 호출 4단(LLM·VLM·이미지생성·S3) 직렬 의존이라 한 단의 일시 실패가 전체 파이프라인을 무력화하므로 회복 여유를 늘렸다.)
6. **타임존** — `now` 미주입 시 UTC 기준. DB 저장 시점에 호출자가 KST 변환 책임.
7. **VLM 외형 묘사 영속화** — `vlm_result.appearance_description` 을 `CharacterEntity.appearance_description` 으로 매핑하여 DB(`characters.appearance_description TEXT NULL`)에 저장. 사유: 재생성 시 외형 일관성 유지 + 퀘스트/피드 생성에서 VLM 재호출 없이 외형 참조. 텍스트-only 경로 및 VLM degrade-on-fail 시는 `None`.
