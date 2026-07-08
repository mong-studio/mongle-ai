#!/usr/bin/env python3
"""Qwen2.5-7B QLoRA SFT — unsloth·trl 없이 transformers Trainer + peft 만 사용.

unsloth 2026.6.1 이 trl 과 안 맞아 eos 를 '<EOS_TOKEN>' sentinel 로 남기는 버그를
근본 회피하기 위해, 가장 안정적인 표준 스택으로 직접 학습한다(파드 종류 무관).

- 4bit(QLoRA) 우선, 실패 시 bf16 폴백. device_map={'':0} 로 전부 GPU 적재(CPU 분산 방지).
- responses-only loss: chat template 의 prompt 접두사 길이만큼 label 을 -100 으로 마스킹
  (assistant 응답 토큰 + eos 에만 loss). 토큰 단위 마스킹이라 문자열 검색 아님.
- 학습 후 valid 일부로 생성→파싱 성공률·EOS 끝맺음률 간이 점검(postcheck_report.json).

실행(깨끗한 PyTorch 파드):
    pip install -U transformers peft bitsandbytes accelerate datasets
    python3 train_plain.py --train sft_train.jsonl --valid sft_valid.jsonl \
        --out outputs/qwen7b-planner-lora --epochs 2 --lr 2e-4
"""
import argparse
import json
import os

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_LEN = 4096
EOS_MARKERS = ("<|im_end|>", "<|endoftext|>")
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
PLAN_PROVENANCES = {"exam-crawl", "daily-latte", "exam-synth"}


def load_rows(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        m = d.get("messages")
        if m and m[-1].get("role") == "assistant" and (m[-1].get("content") or "").strip():
            rows.append(d)
    return rows


def build_tokenize_fn(tok):
    def _tok(d):
        msgs = d["messages"]
        full_text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
        full = tok(full_text, add_special_tokens=False)["input_ids"]
        prompt_text = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
        prompt = tok(prompt_text, add_special_tokens=False)["input_ids"]
        full = full[:MAX_LEN]
        cut = min(len(prompt), len(full))
        labels = [-100] * cut + full[cut:]
        return {"input_ids": full, "attention_mask": [1] * len(full), "labels": labels}

    return _tok


def _load_model(model_name):
    """4bit(QLoRA) 우선 로드, 실패 시 bf16 폴백. 전부 GPU0 에 적재."""
    common = dict(device_map={"": 0}, torch_dtype=torch.bfloat16, trust_remote_code=True)
    try:
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(model_name, quantization_config=bnb, **common)
        model = prepare_model_for_kbit_training(model)
        print("[train] loaded in 4bit (QLoRA)")
        return model, True
    except Exception as exc:  # noqa: BLE001
        print(f"[train] 4bit 로드 실패({exc}); bf16 으로 폴백")
        model = AutoModelForCausalLM.from_pretrained(model_name, **common)
        return model, False


def _quick_eval(model, tok, valid_rows, n=20):
    """valid 일부로 생성 → 파싱 성공률·EOS 끝맺음률 간이 측정(추론 정합성 확인)."""
    model.eval()
    plan_rows = [
        r for r in valid_rows
        if (r.get("meta") or {}).get("provenance") in PLAN_PROVENANCES
    ][:n]
    if not plan_rows:
        return {}
    ok_parse = ok_eos = 0
    for r in plan_rows:
        ids = tok.apply_chat_template(
            r["messages"][:-1], tokenize=True, add_generation_prompt=True, return_tensors="pt"
        ).to(model.device)
        with torch.no_grad():
            gen = model.generate(ids, max_new_tokens=1024, do_sample=False)
        out = tok.decode(gen[0][ids.shape[1]:], skip_special_tokens=False)
        if any(out.rstrip().endswith(m) for m in EOS_MARKERS):
            ok_eos += 1
        try:
            s, e = out.find("{"), out.rfind("}")
            data = json.loads(out[s:e + 1]) if s != -1 and e > s else {}
            if isinstance(data, dict) and "todos" in data and "calendar_events" in data:
                ok_parse += 1
        except Exception:  # noqa: BLE001
            pass
    return {
        "n": len(plan_rows),
        "eos_rate": ok_eos / len(plan_rows),
        "parse_success_rate": ok_parse / len(plan_rows),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--valid", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--grad-accum", dest="grad_accum", type=int, default=4)
    a = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    train_rows = load_rows(a.train)
    valid_rows = load_rows(a.valid) if a.valid else []
    print(f"[train] train={len(train_rows)} valid={len(valid_rows)}")

    _tok = build_tokenize_fn(tok)
    train_ds = Dataset.from_list(train_rows).map(_tok, remove_columns=["messages", "meta"])
    valid_ds = (
        Dataset.from_list(valid_rows).map(_tok, remove_columns=["messages", "meta"])
        if valid_rows else None
    )

    model, is_4bit = _load_model(a.model)
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    lora = LoraConfig(
        r=16, lora_alpha=16, lora_dropout=0.0, bias="none",
        task_type="CAUSAL_LM", target_modules=TARGET_MODULES,
    )
    # EXAONE × transformers 5.x: peft가 임베딩을 못 찾음 → 수동 노출
    try:
        _emb = model.get_input_embeddings()
    except (NotImplementedError, AttributeError):
        _emb = None
    if _emb is None:
        _e = next(m for m in model.modules() if isinstance(m, torch.nn.Embedding))
        model.get_input_embeddings = lambda _e=_e: _e
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    targs = TrainingArguments(
        output_dir=os.path.join(a.out, "checkpoints"),
        per_device_train_batch_size=a.batch,
        gradient_accumulation_steps=a.grad_accum,
        warmup_ratio=0.05,
        num_train_epochs=a.epochs,
        learning_rate=a.lr,
        logging_steps=10,
        optim="adamw_8bit" if is_4bit else "adamw_torch",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        bf16=True,
        seed=42,
        report_to="none",
        save_strategy="no",
        **({"eval_strategy": "no"} if valid_ds is not None else {}),
    )
    collator = DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100)
    trainer = Trainer(
        model=model, args=targs, train_dataset=train_ds, eval_dataset=valid_ds,
        data_collator=collator, processing_class=tok,
    )
    trainer.train()

    os.makedirs(a.out, exist_ok=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    print(f"[train] LoRA 어댑터 저장: {a.out}")

    report = {"adapter": a.out}
    try:
        report["eval_loss"] = (trainer.evaluate() if valid_ds is not None else {}).get("eval_loss")
    except Exception as exc:  # noqa: BLE001
        print(f"[train] evaluate 건너뜀: {exc}")
    try:
        report.update(_quick_eval(model, tok, valid_rows))
    except Exception as exc:  # noqa: BLE001
        print(f"[train] quick_eval 건너뜀: {exc}")

    with open(os.path.join(a.out, "postcheck_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("[train] 점검 리포트:", json.dumps(report, ensure_ascii=False))
    if report.get("eval_loss") is not None and report["eval_loss"] < 0.2:
        print(f"[train] ⚠️ 과적합 의심: eval_loss={report['eval_loss']:.3f} < 0.2")


if __name__ == "__main__":
    main()
