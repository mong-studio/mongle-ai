# 학습 파이프라인 트러블슈팅

## 사건: unsloth LoRA 학습이 `<EOS_TOKEN>` 에서 반복 실패 (2026-06-07)

### 한 줄 요약
`eos_token ('<EOS_TOKEN>')` 에러의 근본 원인은 **버전 비호환이 아니라 import 순서**였다.
`train_lora.py` 에서 **unsloth 를 trl 보다 먼저 import** 하면 끝. transformers 다운그레이드 불필요.

---

### 증상
`SFTTrainer` 생성 시점에 즉사:

```
ValueError: The specified `eos_token` ('<EOS_TOKEN>') is not found in the
vocabulary of the given `processing_class` (Qwen2TokenizerFast)
```

- vLLM 베이스 이미지, 깨끗한 PyTorch 파드 **양쪽에서 동일하게 재발**(그래서 "파드/이미지 문제"로 오인하기 쉬움).
- 변형으로 `<|PAD_TOKEN|>` 미해소 메시지도 함께 나옴.

### 환경
- unsloth `2026.6.1`, transformers `5.5.0`, trl 최신, torch `2.10.0+cu128`
- Qwen2.5-7B-Instruct, RTX 4090 24GB, CUDA 12.8

---

### ❌ 잘못 짚었던 경로 (증상 치료 - 전부 실패. 반복 금지)
증상이 하나씩 바뀌며 터져서 "버전 조합 문제"로 오판하고 표면만 계속 패치했다:

1. 4bit `"modules dispatched on CPU"` → `--no-4bit`(bf16)로 우회 → 다음 에러로 이동
2. `SFTConfig(max_seq_length=)` 미지원 → `max_length=` 로 변경 (trl 버전차)
3. `SFTTrainer(tokenizer=)` 미지원 → `processing_class=` 로 변경 (trl 버전차)
4. `eos_token='<EOS_TOKEN>'` sentinel - 아래 전부 **효과 없음**:
   - `get_chat_template()` 호출 제거
   - `SFTConfig(eos_token="<|im_end|>")` 명시
   - 생성 후 `sft_config.eos_token = "<|im_end|>"` 로 덮어쓰기
5. "버전 비호환"으로 결론짓고 **unsloth 를 버린 뒤** `train_plain.py`(transformers Trainer + peft) 작성
   → 동작은 하지만 **근본 원인 오판**. (train_plain.py 는 폴백으로 보존)

> 교훈: 증상이 계속 바뀌며 터지면 표면 패치 중이라는 신호다. 한 발 물러나
> "이 라이브러리의 **전제 조건**(import 순서·초기화 순서)이 뭔가"를 **공식 이슈**에서 확인하라.

---

### ✅ 근본 원인
unsloth 는 **import 되는 순간** `trl.SFTConfig` / `SFTTrainer` 를 몽키패치한다(unsloth_zoo).
이 패치가 토크나이저의 eos/pad 처리를 담당하는데, **trl 을 unsloth 보다 먼저 import 하면**
패치가 어긋나 `eos_token` 이 실제 토큰(`<|im_end|>`)으로 치환되지 못하고
`<EOS_TOKEN>` 이라는 placeholder 문자열로 남는다. → trl 이 "vocab에 없는 토큰"이라며 거부.

문제의 import (수정 전):

```python
from datasets import Dataset
from trl import SFTConfig, SFTTrainer    # ← trl 먼저  (버그의 원인)
from unsloth import FastLanguageModel    # ← unsloth 나중
```

### 출처 (공식)
- **unsloth#2797** - maintainer:
  *"we expect for unsloth to always be imported first because of the patching we're doing.
  So yes, please always import unsloth first."*
- **StackOverflow 79663362** - 동일 에러(trl 0.18.2 + unsloth 2025.6.2).
  **버전은 그대로 두고 import 순서만 고쳐서 해결.**

### 수정 (한 줄 재배치)
`sft_pipeline/train/train_lora.py` `main()` 내부:

```python
# unsloth 를 trl/transformers 보다 "반드시 먼저" import.
# (근본 원인 - unsloth#2797 maintainer: "always import unsloth first")
from unsloth import FastLanguageModel
from unsloth.chat_templates import train_on_responses_only
from datasets import Dataset
from trl import SFTConfig, SFTTrainer
```

> 주의: `dataset.py` 등 module-top import 가 transformers/trl 를 끌어오면 그것도 unsloth 보다
> 앞서므로 동일 문제가 생긴다. 다행히 `dataset.py` 는 순수 `json`/`pathlib` 만 쓴다(검증됨).
> 4번에서 넣었던 방어 패치(eos 덮어쓰기 등)는 import 순서가 맞으면 트리거되지 않는 무해한 잔재.

---

### 검증 결과
import 순서 수정 후 **동일 파드·동일 버전(transformers 5.5.0)** 에서:

- `SFTTrainer` 생성 통과 - **과거 사망 지점 돌파** (가장 중요한 신호)
- Qwen2.5-7B QLoRA 4bit, trainable `40.4M / 7.66B = 0.53%` (정상 LoRA 비율)
- 2081 샘플 × 2 epoch = 522 steps, ~1.6s/step
- loss 매끄럽게 수렴: epoch1 `1.325 → 0.80 → 0.45 → 0.30 → 0.21`, grad_norm 0.2~0.6 안정, NaN 없음

> `eval_loss < 0.2` 과적합 경고 해석 주의: 출력이 **고정 JSON 구조**라 구조 학습만으로도
> train loss 는 자연히 낮아진다. 낮은 train loss ≠ 무조건 과적합. 진짜 기준은 **validation
> `eval_loss` + `parse_success_rate`**(처음 보는 요청에 올바른 JSON 생성하면 일반화 OK).

---

### 재현 절차 (RunPod)
파드 터미널이 긴 붙여넣기를 망가뜨리므로 **모든 코드는 파일/번들로 전달**한다.

1. 로컬에서 번들: `tar czf trainkit2.tgz run5.sh train_lora.py postcheck.py`
2. 전송: `runpodctl send trainkit2.tgz` → 출력된 code 확보
3. 파드:
   ```bash
   cd /workspace
   runpodctl receive <code>
   tar --no-same-owner -xzf trainkit2.tgz -C /workspace   # macOS chown 경고는 무해
   bash /workspace/run5.sh 2>&1 | tee /workspace/train.log
   ```
4. `run5.sh` 흐름: 패치본 복사 → `2/5 import order OK` 검증 → (데이터 없으면 S3 다운) → 학습 → postcheck
5. 산출물 회수: `outputs/qwen7b-planner-lora`(어댑터) + `outputs/postcheck_report.json`
   ```bash
   cd /workspace/outputs && tar czf adapter.tgz qwen7b-planner-lora postcheck_report.json
   runpodctl send /workspace/outputs/adapter.tgz
   ```

### 데이터/산출물 위치
- 입력: S3 `mongle-village-prod-962214557220-ap-northeast-2-an` / `mongle-village/sft/daily/{sft_train,sft_valid}.jsonl`
- 어댑터: `outputs/qwen7b-planner-lora/` (LoRA 가중치 + 토크나이저)
- 점검 리포트: `outputs/postcheck_report.json` → `finetune_report.ipynb` 에 실측 주입
