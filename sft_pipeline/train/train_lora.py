"""Qwen2.5-7B LoRA SFT (unsloth).

teacher(14B)로 합성한 플래닝 데이터로 제품 서빙 모델(Qwen2.5-7B)을 LoRA 파인튜닝한다.
토큰화·마스킹·EOS·packing 은 unsloth/trl 에 위임한다(sft-coherence: 검증된 프레임워크 사용,
토큰 레벨 정합성 직접 구현 금지). 여기서는 데이터 로딩·LoRA 설정·responses-only loss 구성만 한다.

핵심 정합성 포인트:
- responses-only loss: assistant 응답 토큰에만 loss(`train_on_responses_only`, Qwen 마커 기준).
- 학습 == 서빙 chat template: `get_chat_template(..., "qwen-2.5")` 단일 정의에서 파생.
- 빈 assistant 샘플 제외는 dataset.load_messages 에서 처리(label 0개 방지).

실행(RunPod GPU, PyTorch 템플릿에서):
    pip install "unsloth[colab-new]" trl peft accelerate bitsandbytes datasets
    python -m sft_pipeline.train.train_lora \
        --train sft_pipeline/data/generated/sft_train.jsonl \
        --valid sft_pipeline/data/generated/sft_valid.jsonl \
        --out outputs/qwen7b-planner-lora

unsloth/trl 버전에 따라 일부 인자명이 다를 수 있다(주석 참고).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sft_pipeline.train.dataset import load_messages

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_SEQ_LEN = 4096
# Qwen2.5 chat template 의 턴 마커 — responses-only 마스킹 기준(문자열 아닌 템플릿 마커 기반).
QWEN_INSTRUCTION_PART = "<|im_start|>user\n"
QWEN_RESPONSE_PART = "<|im_start|>assistant\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qwen2.5-7B LoRA SFT (unsloth)")
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--valid", default=None, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="LoRA 어댑터 저장 경로")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-seq-len", dest="max_seq_len", type=int, default=MAX_SEQ_LEN)
    parser.add_argument("--epochs", type=float, default=2.0, help="1~3 권장")
    parser.add_argument("--lr", type=float, default=2e-4, help="LoRA 권장 ~2e-4")
    parser.add_argument("--batch", type=int, default=2, help="device당 배치")
    parser.add_argument("--grad-accum", dest="grad_accum", type=int, default=4)
    parser.add_argument("--lora-r", dest="lora_r", type=int, default=16)
    parser.add_argument("--lora-alpha", dest="lora_alpha", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--load-in-4bit", dest="load_in_4bit", action="store_true", default=True)
    parser.add_argument("--no-4bit", dest="load_in_4bit", action="store_false")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # GPU 없는 환경(테스트·import)에서 모듈이 깨지지 않도록 무거운 의존성은 함수 안에서 import.
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import get_chat_template, train_on_responses_only

    train_rows = load_messages(args.train)
    if not train_rows:
        raise SystemExit(f"[train] 학습 샘플이 비었습니다: {args.train}")
    valid_rows = load_messages(args.valid) if args.valid else []

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model,
        max_seq_length=args.max_seq_len,
        dtype=None,  # 자동(bf16/fp16)
        load_in_4bit=args.load_in_4bit,
    )
    tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")

    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.0,
        bias="none",
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        use_gradient_checkpointing="unsloth",
        random_state=args.seed,
    )

    def _format(batch: dict) -> dict:
        # 학습 == 서빙 템플릿: 같은 chat template 로 렌더(직렬화는 학습 직전 1회).
        texts = [
            tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            for msgs in batch["messages"]
        ]
        return {"text": texts}

    train_ds = Dataset.from_list(train_rows).map(_format, batched=True)
    valid_ds = Dataset.from_list(valid_rows).map(_format, batched=True) if valid_rows else None

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=valid_ds,
        args=SFTConfig(
            dataset_text_field="text",
            max_seq_length=args.max_seq_len,
            per_device_train_batch_size=args.batch,
            gradient_accumulation_steps=args.grad_accum,
            warmup_ratio=0.05,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            logging_steps=10,
            optim="adamw_8bit",
            weight_decay=0.01,
            lr_scheduler_type="linear",
            seed=args.seed,
            output_dir=str(args.out / "checkpoints"),
            report_to="none",
            **({"eval_strategy": "epoch"} if valid_ds is not None else {}),
        ),
    )

    # responses-only loss: assistant 토큰에만 학습(user 발화 모방 방지).
    trainer = train_on_responses_only(
        trainer,
        instruction_part=QWEN_INSTRUCTION_PART,
        response_part=QWEN_RESPONSE_PART,
    )

    trainer.train()

    args.out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(args.out))
    tokenizer.save_pretrained(str(args.out))
    print(f"[train] LoRA 어댑터 저장: {args.out}")
    print(
        "[train] 학습 후 점검: validation loss 확인(0.2 미만이면 과적합 경고), EOS 스모크 테스트, "
        "생성물을 plan_schemas.parse_plan 으로 파싱해 성공률 측정(sft-coherence phase 6)."
    )


if __name__ == "__main__":
    main()
