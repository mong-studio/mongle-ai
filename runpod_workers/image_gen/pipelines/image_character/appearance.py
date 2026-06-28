"""
Local VLM appearance-card extraction (Qwen2.5-VL).

Self-contained copy of mascot_pixel_deploy/local_appearance.py, trimmed to
just the card-extraction part. The original file also has
build_sprite_prompt_from_card/build_mascot_prompt_from_card for the
sprite-LoRA img2img path, which this pipeline doesn't use -- character_gen.py
has its own build_visual_prompt() for the character-LoRA txt2img path
instead. If local_appearance.py's extraction logic changes, this copy must
be updated by hand to match.
"""

from __future__ import annotations

import gc
import json
import re
from typing import Any

from PIL import Image

DEFAULT_MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"

APPEARANCE_PROMPT = """
Look at the attached simplified mascot image and write a visual appearance card
for a cute pixel-art redraw model.

The goal is not exact object recognition. The goal is to preserve the visible
plush design: simple shape, main colors, face layout, outfit, and accessories.

Return ONLY one valid JSON object with exactly these keys:
{
  "id": "runtime",
  "object_type": string,
  "character_type": string,
  "character_summary": string,
  "main_colors": string[],
  "secondary_colors": string[],
  "face": string,
  "body": string,
  "pose": string,
  "outfit": string,
  "ears_arms": string,
  "accessories": string[],
  "silhouette": string,
  "must_preserve": string[],
  "sprite_notes": string[]
}

Rules:
- Be concrete, visual, and conservative.
- Describe only visible design traits from the mascot image.
- Prefer visible traits over guessed symbolic identity. Shape/color/face/outfit
  are more important than naming the object.
- character_type must be a safe base identity for generation:
  cat, dog, bear, monkey, gorilla-like plush, bird, duck, rabbit, dolphin,
  whale, squid, octopus, cuttlefish, or another animal ONLY if it is clear
  from multiple visible cues.
- If identity is ambiguous AND there are no strong animal cues, use a broad
  safe label such as "abstract plush", "plush mascot", "animal-like plush",
  "object-shaped plush", or "plush charm".
- Do not demote a readable animal plush to "abstract plush". If the face panel,
  muzzle, ears, long arms, beak, tail, fins, tentacles, or body proportions
  point to a common animal, keep that animal identity and describe uncertain
  parts visually.
- Do NOT use food/fruit/object names such as avocado, eggplant, bread, cloud,
  pillow, pouch, or star as character_type unless the design is unmistakably
  that object and there is no better plush-mascot description. For a face on a
  colored oval or shape, prefer "abstract plush" or "plush charm".
- Avoid food/fruit/object names in character_summary, body, must_preserve, and
  sprite_notes too unless the plush is unmistakably that object. If a shape
  merely resembles a fruit/object, describe the visible geometry instead.
- Clothing, costumes, themed hoods, striped suits, blankets, shirts, and vests
  belong in outfit, not character_type.
- If a base animal wears a themed costume, keep character_type as the base
  animal or "animal-like plush"; put the theme in outfit/accessories.
- Never turn a costume into body anatomy. Example: bee costume means
  "wearing bee-themed outfit", not bee or insect character.
- For ambiguous rounded side bumps or lower bumps, prefer silhouette/detail
  wording over anatomy words. Mention arms or legs only when they are clearly
  visible and important.
- Avoid turning plush shape bumps into separate cartoon limbs. Prefer
  "integrated side bumps", "lower rounded bumps", or "attached plush
  appendages" unless clear hands, feet, or separate limbs are a defining source
  feature.
- If several lower appendages are visible on a sea-creature plush, describe
  them as tentacles when they support squid/octopus/cuttlefish identity.
- Mention face layout, eye shape/color, nose/mouth, cheek patches, face panel
  shape, ears, tail, wings, bows, tags, loops, patterns, and color blocks when
  visible.
- For sea-animal plushies, preserve the side-view body, tail, fins, dorsal fin,
  white belly patch, and single visible eye. Do NOT reinterpret fins as ears,
  arms, or rabbit-like parts.
- For squid/octopus/cuttlefish plushies, preserve the tall mantle/head,
  tentacles at the bottom, side fins or flaps, simple face, and main color.
  Do NOT call them banana or fruit.
- Mention proportions and silhouette in simple pixel-friendly words.
- Avoid fabric/fur texture, wrinkles, stains, lighting, shadows, camera angle,
  or realistic material. Convert them to simple pixel traits.
- Keep must_preserve as 6 to 10 short visual phrases that a pixel sprite must
  keep.
- Keep sprite_notes as 2 to 5 short practical notes for 64x64 pixel sprite
  rendering.
- If a field is not visible, use an empty string or empty list.
- Do not invent hidden details.

Examples:
- Purple oval plush with yellow face and red mouth:
  character_type="abstract plush", body="purple oval body with large yellow
  oval face patch", must_preserve includes "purple oval body", "yellow face
  patch", "red smiling mouth". Do NOT call it avocado or food.
- Brown monkey or gorilla-like plush with long arms and cream muzzle:
  character_type="monkey" or "gorilla-like plush", face includes "cream face
  patch/muzzle", ears_arms includes "long arms". Do NOT call it abstract plush.
- Yellow squid or cuttlefish plush with bottom tentacles:
  character_type="squid" or "cuttlefish", body includes "tall curved mantle",
  ears_arms includes "short bottom tentacles and side flaps". Do NOT call it
  banana.
- Long yellow curved plush with a simple face and no clear tentacles:
  character_type="abstract plush" or "plush mascot", body="long curved yellow
  body with flat rounded top and small lower bumps". Do NOT call it banana.
- Light blue dolphin or whale plush:
  character_type="dolphin" or "whale", body includes "long horizontal body",
  ears_arms includes "fins and dorsal fin". Do NOT add ears or rabbit traits.
- Bird or duck wearing a bee outfit:
  character_type="bird" or "duck" if clear, outfit="bee-themed outfit with
  yellow and black stripes". Do NOT call it bee or insect.
- Cat-shaped pillow:
  character_type="cat", body="pillow-like rounded body". Do NOT call the
  character_type pillow.
""".strip()

SOURCE_PHOTO_APPEARANCE_PROMPT = """
Look at the attached real photo of a plush toy, soft object, charm, or mascot
and write a visual appearance card for a cute pixel-art redraw model.

The goal is not exact object recognition. The goal is to preserve the visible
plush design so a later model can draw one cute pixel-art character from it:
simple shape, main colors, face layout, outfit, and accessories.

Return ONLY one valid JSON object with exactly these keys:
{
  "id": "runtime",
  "object_type": string,
  "character_type": string,
  "character_summary": string,
  "main_colors": string[],
  "secondary_colors": string[],
  "face": string,
  "body": string,
  "pose": string,
  "outfit": string,
  "ears_arms": string,
  "accessories": string[],
  "silhouette": string,
  "must_preserve": string[],
  "sprite_notes": string[]
}

Rules:
- Ignore the room, floor, hand, lighting, shadow, camera angle, photo
  background, fabric texture, wrinkles, stains, blur, or tiny noisy detail.
- Be concrete, visual, and conservative.
- Prefer visible traits over guessed symbolic identity. Shape/color/face/outfit
  are more important than naming the object.
- character_type must be a safe base identity for generation:
  cat, dog, bear, monkey, gorilla-like plush, bird, duck, rabbit, dolphin,
  whale, squid, octopus, cuttlefish, or another animal ONLY if it is clear
  from multiple visible cues.
- If identity is ambiguous AND there are no strong animal cues, use a broad
  safe label such as "abstract plush", "plush mascot", "animal-like plush",
  "object-shaped plush", or "plush charm".
- Do not demote a readable animal plush to "abstract plush". If the face panel,
  muzzle, ears, long arms, beak, tail, fins, tentacles, or body proportions
  point to a common animal, keep that animal identity and describe uncertain
  parts visually.
- Do NOT use food/fruit/object names such as avocado, eggplant, bread, cloud,
  pillow, pouch, or star as character_type unless the design is unmistakably
  that object and there is no better plush-mascot description. For a face on a
  colored oval or shape, prefer "abstract plush" or "plush charm".
- Avoid food/fruit/object names in character_summary, body, must_preserve, and
  sprite_notes too unless the plush is unmistakably that object. If a shape
  merely resembles a fruit/object, describe the visible geometry instead.
- Clothing, costumes, themed hoods, striped suits, blankets, shirts, and vests
  belong in outfit, not character_type.
- If a base animal wears a themed costume, keep character_type as the base
  animal or "animal-like plush"; put the theme in outfit/accessories.
- Never turn a costume into body anatomy. Example: bee costume means
  "wearing bee-themed outfit", not bee or insect character.
- Pillow/cushion/blanket should usually describe body form or outfit, not
  character_type, when there is an animal-like face.
- For ambiguous rounded side bumps or lower bumps, prefer silhouette/detail
  wording over anatomy words. Mention arms or legs only when they are clearly
  visible and important.
- Avoid turning plush shape bumps into separate cartoon limbs. Prefer
  "integrated side bumps", "lower rounded bumps", or "attached plush
  appendages" unless clear hands, feet, or separate limbs are a defining source
  feature.
- If several lower appendages are visible on a sea-creature plush, describe
  them as tentacles when they support squid/octopus/cuttlefish identity.
- Preserve simple readable visual details: color patches, face panel shape,
  white belly patch, zigzag edges, stripes, hearts, stars, collars, bows, tags,
  loops, ears, tails, side bumps, and readable color blocks.
- For sea-animal plushies, preserve the side-view body, tail, fins, dorsal fin,
  white belly patch, and single visible eye. Do NOT reinterpret fins as ears,
  arms, or rabbit-like parts.
- For squid/octopus/cuttlefish plushies, preserve the tall mantle/head,
  tentacles at the bottom, side fins or flaps, simple face, and main color.
  Do NOT call them banana or fruit.
- Convert photo texture into simple pixel-art traits. Do not request fur
  texture, fabric texture, gradients, realistic material, or tiny noisy detail.
- Keep must_preserve as 6 to 10 short visual phrases that a pixel sprite must
  keep.
- Keep sprite_notes as 2 to 5 short practical notes for 64x64 pixel sprite
  rendering.
- If a field is not visible, use an empty string or empty list.
- Do not invent hidden details.

Examples:
- Purple oval plush with yellow face and red mouth:
  character_type="abstract plush", body="purple oval body with large yellow
  oval face patch", must_preserve includes "purple oval body", "yellow face
  patch", "red smiling mouth", "tiny black eyes", "small hanging loop". Do
  NOT call it avocado or food.
- Brown monkey or gorilla-like plush with long arms and cream muzzle:
  character_type="monkey" or "gorilla-like plush", face includes "cream face
  patch/muzzle", ears_arms includes "long arms". Do NOT call it abstract plush.
- Yellow squid or cuttlefish plush with bottom tentacles:
  character_type="squid" or "cuttlefish", body includes "tall curved mantle",
  ears_arms includes "short bottom tentacles and side flaps". Do NOT call it
  banana.
- Long yellow curved plush with a simple face and no clear tentacles:
  character_type="abstract plush" or "plush mascot", body="long curved yellow
  body with flat rounded top and small lower bumps". Do NOT call it banana.
- Light blue dolphin or whale plush:
  character_type="dolphin" or "whale", body includes "long horizontal body",
  ears_arms includes "fins and dorsal fin". Do NOT add ears or rabbit traits.
- Bird or duck wearing a bee outfit:
  character_type="bird" or "duck" if clear, outfit="bee-themed outfit with
  yellow and black stripes". Do NOT call it bee or insect.
- Cat plush wearing an orange blanket or shirt:
  character_type="cat", outfit="orange outfit", body mentions white face/body
  and white belly patch.
- Cat-shaped pillow:
  character_type="cat", body="pillow-like rounded body". Do NOT call the
  character_type pillow.
""".strip()


def extract_json_object(raw: str) -> dict[str, Any]:
    clean = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", clean, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        clean = fenced.group(1).strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in VLM output: {raw[:200]!r}")
    return json.loads(clean[start : end + 1])


def _as_string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _clean_optional_visual_text(value) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if lowered in {"none", "n/a", "not visible", "no visible", "no visible ears or arms."}:
        return ""
    if lowered.startswith("no visible ears") and "arms" not in lowered:
        return ""
    return text


def _pixel_safe_phrase(text: str) -> str:
    replacements = {
        "Use soft shading for texture.": "Use simple pixel shading, not smooth texture.",
        "Use soft shading for texture": "Use simple pixel shading, not smooth texture",
        "soft texture appearance": "soft rounded appearance",
        "soft and fluffy appearance": "soft rounded appearance",
        "fluffy body": "rounded body with smooth solid color",
        "fluffy": "soft rounded",
        "fur texture": "smooth solid color",
        "furry texture": "smooth solid color",
        "textured fur": "smooth solid color",
        "Ensure leaf patterns are clear and distinct.": "Simplify patterns into a few readable pixel clusters.",
        "Ensure leaf patterns are clear and distinct": "Simplify patterns into a few readable pixel clusters",
    }
    result = str(text or "").strip()
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def normalize_card(card: dict[str, Any]) -> dict[str, Any]:
    object_type = str(card.get("object_type", "")).strip()
    if object_type.lower() in {"", "mascot", "character"}:
        object_type = "soft object"
    character_type = str(card.get("character_type", "")).strip() or f"{object_type} mascot"
    if character_type.lower() in {"mascot", "cute creature", "character"}:
        character_type = f"{object_type} mascot"

    return {
        "id": str(card.get("id") or "runtime"),
        "object_type": object_type,
        "character_type": character_type,
        "character_summary": _pixel_safe_phrase(str(card.get("character_summary", ""))),
        "main_colors": _as_string_list(card.get("main_colors")),
        "secondary_colors": _as_string_list(card.get("secondary_colors")),
        "face": str(card.get("face", "")),
        "body": _pixel_safe_phrase(str(card.get("body", ""))),
        "pose": str(card.get("pose", "")),
        "outfit": _clean_optional_visual_text(card.get("outfit")),
        "ears_arms": _clean_optional_visual_text(card.get("ears_arms")),
        "accessories": _as_string_list(card.get("accessories")),
        "silhouette": str(card.get("silhouette", "")),
        "must_preserve": [_pixel_safe_phrase(item) for item in _as_string_list(card.get("must_preserve"))],
        "sprite_notes": [_pixel_safe_phrase(item) for item in _as_string_list(card.get("sprite_notes"))],
    }


def load_model(model_id: str = DEFAULT_MODEL_ID, use_4bit: bool = True):
    import torch
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    model_kwargs = {
        "device_map": "auto",
        "trust_remote_code": True,
    }
    if use_4bit:
        from transformers import BitsAndBytesConfig

        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
    else:
        model_kwargs["torch_dtype"] = torch.float16

    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, **model_kwargs).eval()
    processor = AutoProcessor.from_pretrained(
        model_id,
        min_pixels=256 * 28 * 28,
        max_pixels=512 * 28 * 28,
        trust_remote_code=True,
    )
    return model, processor


def unload_model(model, processor) -> None:
    del model, processor
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def generate_card(
    image: Image.Image,
    model,
    processor,
    max_new_tokens: int = 512,
    appearance_prompt: str = APPEARANCE_PROMPT,
) -> tuple[dict[str, Any], str]:
    import torch
    from qwen_vl_utils import process_vision_info

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image.convert("RGB")},
                {"type": "text", "text": appearance_prompt},
            ],
        }
    ]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )

    target_device = "cuda" if torch.cuda.is_available() else "cpu"
    inputs = inputs.to(target_device)
    with torch.no_grad():
        generated = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )

    trimmed = generated[0][inputs.input_ids.shape[1] :]
    raw = processor.decode(trimmed, skip_special_tokens=True).strip()
    return normalize_card(extract_json_object(raw)), raw
