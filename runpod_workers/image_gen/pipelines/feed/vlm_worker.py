"""Short-lived Korean quest translation worker.

Character appearance is supplied by the canonical JSON profile. This worker
never analyzes or changes the character identity.
"""

from __future__ import annotations

import gc
import json
import sys


QUEST_MODEL_ID = "Qwen/Qwen2-VL-7B-Instruct"

QUEST_SYSTEM = """You are a BACKGROUND scene prompt writer for Mongle Village, a cozy pastel sky island pixel art village.

The character is added later as a separate sprite, so describe ONLY the setting and props of the completed activity — with NO character in it.

Convert a Korean quest completion message into a short English background description.

Rules:
- Describe the environment and objects that make the completed activity recognizable.
- Do NOT mention any character, animal, person, creature, mascot, or body part.
- Keep the lower-center foreground open and uncluttered (a character is placed there later).
- Cozy pastel sky island village style.
- Use 12-20 words.
- Output only the English background description.

Examples:
Input: 공원에서 30분 달리기를 완료했어요
Output: a winding cloud meadow path with flower markers and a small finish flag, open grassy foreground

Input: 오늘 책 한 권을 다 읽었어요
Output: a cozy reading nook with an open storybook on a cushion under a blossoming cloud tree
"""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def load_quest_model():
    import torch
    from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2VLForConditionalGeneration

    log(f"Loading quest translation model: {QUEST_MODEL_ID}")
    processor = AutoProcessor.from_pretrained(QUEST_MODEL_ID, max_pixels=256 * 256)
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        QUEST_MODEL_ID,
        torch_dtype=torch.float16,
        quantization_config=BitsAndBytesConfig(load_in_8bit=True),
        device_map="auto",
    ).eval()
    return model, processor


def translate_quest(quest_ko: str, model, processor) -> str:
    import torch

    messages = [
        {"role": "system", "content": QUEST_SYSTEM},
        {"role": "user", "content": quest_ko},
    ]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], padding=True, return_tensors="pt").to("cuda")
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=60,
            do_sample=False,
            temperature=None,
            top_p=None,
            pad_token_id=processor.tokenizer.eos_token_id,
        )
    generated = outputs[0][inputs.input_ids.shape[1]:]
    result = processor.decode(generated, skip_special_tokens=True).strip()
    del inputs, outputs
    gc.collect()
    torch.cuda.empty_cache()
    return result


def unload_quest_model(model, processor) -> None:
    import torch

    del model, processor
    gc.collect()
    torch.cuda.empty_cache()


def main() -> None:
    if len(sys.argv) != 2:
        log("usage: python -m pipelines.feed.vlm_worker <batch_json_path>")
        raise SystemExit(1)

    with open(sys.argv[1], encoding="utf-8") as batch_file:
        cases = json.load(batch_file)

    model, processor = load_quest_model()
    try:
        results = []
        for case in cases:
            quest_en = translate_quest(case["quest_ko"], model, processor)
            log(f"[{case['name']}] {case['quest_ko']} -> {quest_en}")
            results.append({"name": case["name"], "quest_en": quest_en})
    finally:
        unload_quest_model(model, processor)

    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
