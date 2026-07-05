# Planner SFT v3 — teacher 증류 재시도

스펙: `docs/superpowers/specs/2026-07-04-planner-sft-v3-design.md`.
기존 운영 어댑터·`LORA_PLANNER_REPO`·V2 디렉토리는 절대 수정하지 않는다.

## 실행 순서 (저장소 루트에서)

1. **오프라인 테스트**: `uv run pytest sft_pipeline/experiments/planner_sft_v3/tests/ -v`
2. **증류 (비용 발생, OPENAI_API_KEY 필요)**:
   ```bash
   uv run python -m sft_pipeline.experiments.planner_sft_v3.distill_dataset \
     --out sft_pipeline/experiments/planner_sft_v3/data/planner_sft_v3_gold.jsonl \
     --holdout-out sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl
   ```
   중단돼도 재실행하면 캐시(`outputs/planner-sft-v3-distill-cache/`)에서 재개.
   먼저 `--limit 20` 스모크로 드롭 사유 분포를 확인하고 teacher 프롬프트를 조정할 것.
3. **학습 (RunPod 24GB, tmux 안에서)**:
   ```bash
   EXPERIMENT_ROOT=outputs/planner-sft-v3-run1 \
   bash sft_pipeline/experiments/planner_sft_v3/train_runpod.sh
   ```
   train_loss < 0.3 이면 스크립트가 중단한다(암기 경고). 어댑터는 즉시 S3 백업.
4. **A/B 관문**: `build_ab_notebook.py` 로 노트북 생성 → GPU pod 에서
   `jupyter nbconvert --execute --inplace` → **출력 박힌 노트북을 `git add -f` 커밋**.

## 승격 기준 (스펙 §7·§9)

- `eval_report.json` 의 게이트 전부 통과 **그리고** A/B 의미 평균 LoRA ≥ base → 승격 자격.
- 미달이면 기각 — eval_report 와 A/B 노트북이 곧 기각 근거 기록이다. 재학습은
  드롭 사유 분포(`*.report.json`)를 보고 데이터부터 고친 뒤에만.

## 승격 절차 (통과 시에만)

V2 README §5~§6 절차 그대로: 신규 HF repo `bigmooon/exaone-planner-sft-v3` 업로드 →
RunPod 템플릿 복제 테스트 엔드포인트 → 문제 없으면 운영 `LORA_PLANNER_REPO` 변경.
롤백 = env 원복.

## 함정

- `sft_pipeline/` 은 `.gitignore` — 신규 파일은 항상 `git add -f`.
- Pod 재실행은 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`.
- 스모크·평가는 학습 *후*에만 (커널이 VRAM 물면 학습 OOM).
