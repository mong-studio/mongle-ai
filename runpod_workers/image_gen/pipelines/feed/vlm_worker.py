"""Short-lived Korean quest translation worker.

Character appearance is supplied by the canonical JSON profile. This worker
never analyzes or changes the character identity.
"""

from __future__ import annotations

import gc
import json
import sys


QUEST_MODEL_ID = "Qwen/Qwen2-VL-7B-Instruct"

QUEST_SYSTEM = """You are a scene prompt writer for Mongle Village, a cozy pastel pixel art world.

Convert a Korean quest completion message into a short English scene that clearly shows ONE character DOING that activity.

Rules:
- Start with the character's visible action, and include the KEY PROPS/objects that make the activity unmistakable (e.g. reading -> an open storybook; cooking -> a steaming pot).
- The activity is the main subject and must be central; keep the background simple and secondary so it never hides the action.
- Match the setting to the activity itself (library, kitchen, park, ...) — do not force one fixed location.
- Anatomy-neutral verbs only (reading, running, cooking, watering, resting). Do not mention arms, legs, hands, feet, or paws.
- One character only. Cozy pastel pixel-art mood.
- Use 12-22 words.
- Output only the English scene description.

Examples:
Input: 도서관에서 책 읽기를 완료했어요
Output: reading an open storybook at a cozy library desk surrounded by tall bookshelves

Input: 공원에서 30분 달리기를 완료했어요
Output: running along a grassy park path past flower markers and a small finish flag
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
