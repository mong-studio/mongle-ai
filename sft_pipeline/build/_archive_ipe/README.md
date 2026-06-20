# `_archive_ipe/` — 정보처리기사(IPE) 반복 실험 보관소 (동결)

이 폴더는 첫 시험 데이터셋(정보처리기사)을 만들며 거친 **v1 → v2b 어댑터 반복 실험의 1회성 스크립트**다.
재사용 파이프라인(`build/lib/`, `build/jobs/`)에서 분리해 여기로 옮겼다.

## 왜 지우지 않고 보관하나
- `ipe_sft_dataset_report.ipynb` 에 크롤→구조화→학습→평가 전 과정과 연도 오타·C5 분기 디버깅 history 가 담겨 있다.
  새 시험 데이터를 만들 때 **같은 함정을 피하려고** 참고한다.
- v4 데이터는 실제 출시된 v2b 어댑터(`bigmooon/qwen2.5-7b-mongle-planner-ko-lora`, HuggingFace)의 학습에 쓰였다.

## 주의
- 이 폴더 코드는 **유지보수하지 않는다.** import 경로는 `sft_pipeline.build._archive_ipe.*` / `sft_pipeline.build.lib.*` 로 갱신해 두었지만, 라이브러리가 더 바뀌면 깨질 수 있다.
- `filter_dataset_by_kind.py` 는 이미 삭제된 `sft_pipeline.train.postcheck` 에 의존해 동작하지 않는다(참고용으로만 보존).
- 새 작업은 항상 `build/lib/` + `build/jobs/` 로 한다. 전체 사용법은 `sft_pipeline/HANDOVER.ipynb` 참고.
