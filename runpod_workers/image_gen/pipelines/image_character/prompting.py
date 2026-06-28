"""
Generate a pixel character from an appearance JSON using the existing
text_character image generator.

This path is intentionally text-only:

    appearance.json -> concise visual prompt -> character LoRA txt2img

No mascot image is used as an init image, so Stage A texture/sketch artifacts
do not get carried into the result.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TEXT2IMG_CONFIGS: dict[str, dict[str, Any]] = {
    "A_text_soft": {"lora_scale": 0.75, "steps": 8, "lcm": True, "seed": 42},
    "B_text_default": {"lora_scale": 0.90, "steps": 8, "lcm": True, "seed": 42},
    "C_text_strong": {"lora_scale": 1.05, "steps": 8, "lcm": True, "seed": 42},
}

BASE_STYLE_SUFFIX = (
    "monglestyle, true 32-bit pixel art sprite, pixelated game sprite, "
    "crisp pixel edges, clean pixel outline, simple pixel shading, limited color palette, "
    "single cute mascot character, clean readable silhouette, "
    "cute face with round dot eyes and small dot nose, "
    "full body, centered, front view, isolated on pure white background"
)

SOFT_STYLE_SUFFIX = (
    "monglestyle, true 32-bit pixel art sprite, pixelated game sprite, "
    "crisp pixel edges, clean pixel outline, simple pixel shading, limited color palette, "
    "single cute mascot character, clean readable silhouette, "
    "cute face with round dot eyes and small dot nose, "
    "full body, centered, front view, isolated on pure white background"
)

PIXEL_STYLE_SUFFIX = SOFT_STYLE_SUFFIX

PROMPT2_SOFT_STYLE_SUFFIX = (
    "true 32-bit pixel art sprite, crisp square pixels, simple pixel shading"
)

PROMPT2_PIXEL_STYLE_SUFFIX = (
    "true 32-bit pixel art sprite, crisp square pixels, simple pixel shading"
)

TEXT2IMG_NEGATIVE = (
    "realistic, photograph, 3d render, smooth illustration, vector art, flat vector icon, "
    "anime, painterly rendering, airbrush shading, smooth gradient shading, "
    "glossy surface, plush photo, fabric texture, fur texture, noisy texture, "
    "non-pixel art, anti-aliased smooth lineart, blurry edges, "
    "creepy, scary, grotesque, realistic insect, compound eyes, mandibles, insect legs, "
    "human-like body, human arms, human legs, oversized head, tiny body, chibi proportions, "
    "separate cartoon arms, separate cartoon legs, visible hands, visible feet, humanoid mascot body, "
    "complex background, repeating pattern, background icons, props, multiple characters, "
    "text, watermark, extra limbs, harsh black outline, low quality, blurry, deformed"
)

RISKY_OBJECT_PHRASES = {
    "resembling a banana": "with a long curved silhouette",
    "resembling banana": "with a long curved silhouette",
    "banana-shaped": "long curved",
    "banana shaped": "long curved",
    "banana-like": "long curved",
    "like a banana": "long curved",
    "banana": "long curved yellow plush",
    "resembling an avocado": "with an oval silhouette",
    "resembling avocado": "with an oval silhouette",
    "avocado-shaped": "oval",
    "avocado shaped": "oval",
    "avocado-like": "oval",
    "like an avocado": "oval",
    "avocado": "oval plush",
    "eggplant-shaped": "long oval",
    "eggplant shaped": "long oval",
    "eggplant-like": "long oval",
    "eggplant": "long oval plush",
}


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _list_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_list_text(value))
    return str(value or "").strip()


def _clean_visual(text: str) -> str:
    result = " ".join(str(text or "").replace("\n", " ").split()).strip(" ,.;:")
    lowered = result.lower()
    if lowered in {"none", "n/a", "not visible", "no visible", "[]"}:
        return ""
    if lowered.startswith("no visible"):
        return ""

    for old, new in RISKY_OBJECT_PHRASES.items():
        result = re.sub(re.escape(old), new, result, flags=re.IGNORECASE)

    replacements = {
        "rounded body with long arms and legs": "rounded body with long plush appendages attached to the body",
        "rounded body with short arms and legs": "rounded body with small rounded side and lower bumps",
        "body with arms and legs": "body with rounded side and lower bumps",
        "arms and legs": "rounded side and lower bumps",
        "long arms extending outward": "long plush appendages attached to the body",
        "long arms extending from the sides": "long plush appendages attached to the body",
        "long arms": "long plush appendages attached to the body",
        "short arms": "small rounded side bumps",
        "arms": "plush side appendages",
        "long limbs": "long plush appendages attached to the body",
        "short limbs": "small rounded appendages",
        "legs": "lower body bumps",
        "feet": "lower rounded tips",
        "legs are visible": "lower bumps are visible",
        "ensure the legs are visible": "keep the lower body bumps visible",
        "human-like limbs": "plush appendages",
        "soft-looking": "rounded",
        "soft looking": "rounded",
        "soft rounded and rounded": "rounded",
        "rounded and rounded": "rounded",
        "furry_": "",
        "fluffy_": "",
        "furry ": "",
        "fluffy ": "",
        "soft rounded": "rounded",
        "smooth silhouette": "clean silhouette",
        "smooth": "",
        "soft": "",
        "orange blanket wrapped around the body": "orange outfit",
        "blanket wrapped around the body": "outfit",
    }
    for old, new in replacements.items():
        result = result.replace(old, new)
    result = result.replace("with a ,", "")
    result = result.replace("with an ,", "")
    result = result.replace(", and rounded", ", rounded")
    result = result.replace("and rounded,", "rounded,")
    result = " ".join(result.split()).strip(" ,.;:-")

    banned = [
        "texture",
        "fabric",
        "wrinkle",
        "wrinkles",
        "stain",
        "stains",
        "spots",
        "noisy",
        "noise",
        "realistic",
        "detailed",
        "wasp-like",
        "wasp anatomy",
        "compound eyes",
        "mandibles",
        "human-like arms",
        "human-like legs",
        "separate hands",
        "separate feet",
    ]
    lowered = result.lower()
    if any(word in lowered for word in banned):
        return ""
    return result


def _pick_type(card: dict[str, Any]) -> str:
    generic_types = {
        "animal",
        "amphibian",
        "mammal",
        "creature",
        "cute animal",
        "soft animal",
        "plush animal",
        "round food",
        "round_food",
        "food mascot",
        "round food mascot",
        "object mascot",
        "round object mascot",
    }
    if card.get("animal_type"):
        value = _clean_visual(_text(card.get("animal_type")))
        if value.lower().replace("_", " ") in generic_types:
            return "round object mascot"
        return value
    for key in ("character_type", "object_type"):
        value = _clean_visual(_text(card.get(key)))
        if value and value.lower() not in {"soft object", "mascot", "character"}:
            value_key = value.lower().replace("_", " ")
            if value_key in generic_types:
                return "round object mascot"
            if _looks_like_costume_theme(card, value):
                return f"round mascot wearing {value.lower().replace('_', ' ')}-themed costume"
            return value
    summary = _clean_visual(_text(card.get("character_summary")))
    return summary or "cute mascot"


def _pick_main_color(card: dict[str, Any]) -> str:
    if card.get("body_color"):
        return _clean_visual(_text(card.get("body_color")))
    colors = [_clean_visual(item) for item in _list_text(card.get("main_colors"))]
    colors = [item for item in colors if item]
    return " and ".join(colors[:2])


def _pick_secondary(card: dict[str, Any]) -> list[str]:
    values = _list_text(card.get("secondary_colors"))
    cleaned = [_clean_visual(item) for item in values]
    return [item for item in cleaned if item][:4]


def _looks_like_costume_theme(card: dict[str, Any], character_type: str) -> bool:
    theme_types = {"bee", "wasp", "hornet", "butterfly", "ladybug", "insect"}
    type_lower = character_type.strip().lower().replace("_", " ")
    if type_lower not in theme_types:
        return False

    fields = [
        card.get("character_summary"),
        card.get("body"),
        card.get("outfit"),
        card.get("ears_arms"),
        card.get("accessories"),
        card.get("must_preserve"),
        card.get("sprite_notes"),
    ]
    blob = " ".join(_text(value).lower() for value in fields if value)
    costume_markers = [
        "costume",
        "outfit",
        "vest",
        "collar",
        "hood",
        "hat",
        "wings",
        "winged",
        "antennae",
        "stripe",
        "stripes",
        "rounded body",
        "round face",
    ]
    return any(marker in blob for marker in costume_markers)


def build_text_character_visual_prompt(card: dict[str, Any]) -> str:
    """Convert deploy-card or text-character card JSON to a concise visual prompt."""
    parts: list[str] = []

    main_color = _pick_main_color(card)
    character_type = _pick_type(card)
    if main_color and character_type:
        parts.append(f"{main_color} {character_type}")
    else:
        parts.append(character_type or main_color or "cute mascot")

    for key in ("body_shape", "body", "head_shape", "silhouette"):
        value = _clean_visual(_text(card.get(key)))
        if value:
            parts.append(value)

    for key in ("eye_style", "face", "nose_mouth", "nose_shape", "mouth_shape", "cheeks"):
        value = _clean_visual(_text(card.get(key)))
        if value:
            parts.append(value)

    for key in ("ear_shape", "ears_arms", "limbs"):
        value = _clean_visual(_text(card.get(key)))
        if value:
            parts.append(value)

    outfit = _clean_visual(_text(card.get("outfit")))
    if outfit:
        parts.append(f"wearing {outfit}")

    secondary = _pick_secondary(card)
    if secondary:
        parts.append("accents: " + ", ".join(secondary))

    accessories = _list_text(card.get("accessories"))
    accessories = [_clean_visual(item) for item in accessories]
    accessories = [item for item in accessories if item and item.lower() not in {"none", "[]"}]
    if accessories:
        parts.append("accessories: " + ", ".join(accessories[:3]))

    features = _list_text(card.get("distinctive_features")) or _list_text(card.get("must_preserve"))
    features = [_clean_visual(item) for item in features]
    features = [item for item in features if item][:5]
    if features:
        parts.append("key features: " + ", ".join(features))

    if outfit or accessories:
        parts.append("costume details stay as clothing, not creature anatomy")
    parts.append("cute toy-like mascot")
    parts.append("simple cute expression")
    parts.append("clean readable silhouette")

    compact: list[str] = []
    for part in parts:
        if part and part not in compact:
            compact.append(part)
    return ", ".join(compact)


def get_style_suffix(config_name: str | None = None) -> str:
    if config_name == "A_text_soft":
        return SOFT_STYLE_SUFFIX
    return BASE_STYLE_SUFFIX


def get_prompt2_style_suffix(config_name: str | None = None) -> str:
    if config_name == "A_text_soft":
        return PROMPT2_SOFT_STYLE_SUFFIX
    return PROMPT2_PIXEL_STYLE_SUFFIX


def build_final_prompt(persona_en: str, config_name: str | None = None) -> str:
    style_suffix = get_style_suffix(config_name)
    return f"{persona_en}, {style_suffix}" if persona_en else style_suffix


def build_prompt_pair_from_card(card: dict[str, Any], config_name: str | None = None) -> tuple[str, str, str]:
    """Build the preferred original-style prompt from appearance fields.

    Keep the prompt close to the first good run: the identity anchor comes
    first, and prompt_2 repeats that anchor with concise appearance details.
    """
    persona_en = build_text_character_visual_prompt(card)
    prompt, prompt_2 = build_prompt_pair(persona_en, config_name=config_name)
    return persona_en, prompt, prompt_2


def build_cute_v2_prompt_pair_from_card(
    card: dict[str, Any],
    config_name: str | None = None,
) -> tuple[str, str, None]:
    """Combine the current appearance card with the earlier, cuter prompt style."""
    del config_name
    persona_en = build_text_character_visual_prompt(card)
    prompt_parts = [
        "monglestyle",
        "32-bit pixel art sprite",
        "hard pixel edges",
        "blocky pixel art",
    ]
    if persona_en:
        prompt_parts.append(persona_en)
    prompt_parts.extend(
        [
            "flat pixel shading",
            "limited color palette",
            "clean readable silhouette",
            "cute simple plush face matching the source expression",
            "single plush mascot sprite",
            "complete source silhouette",
            "centered",
            "source-matched pose and view",
            "pure white background",
        ]
    )
    return persona_en, ", ".join(prompt_parts), None


def build_legacy_v2_exact_prompt_pair_from_card(
    card: dict[str, Any],
    config_name: str | None = None,
) -> tuple[str, str, None]:
    """Use the exact final prompt template from appearance_prompt_v2_full_01."""
    del config_name
    persona_en = build_text_character_visual_prompt(card)
    prompt = (
        "monglestyle, 32-bit pixel art sprite, hard pixel edges, blocky pixel art, "
        f"{persona_en}, flat pixel shading, limited color palette, clean silhouette, "
        "cute face with round dot eyes and small dot nose, full body, centered, "
        "front view, pure white background"
    )
    return persona_en, prompt, None


def build_cute_v2_limb_safe_prompt_pair_from_card(
    card: dict[str, Any],
    config_name: str | None = None,
) -> tuple[str, str, None]:
    """Combine the cute legacy rendering style with the proven limb guard."""
    del config_name
    persona_en = build_text_character_visual_prompt(card)
    prompt = (
        "monglestyle, 32-bit pixel art sprite, hard pixel edges, blocky pixel art, "
        f"{persona_en}, faithful to source mascot, preserve source shape colors face accessories, "
        "flat pixel shading, limited color palette, clean readable silhouette, "
        "cute simple plush face matching the source expression, single plush mascot sprite, "
        "complete source silhouette visible, centered, source-matched pose and view, "
        "pure white background, no humanoid arms or legs"
    )
    return persona_en, prompt, None


def _appendage_state(value: Any) -> tuple[str, str]:
    raw_text = " ".join(_text(value).replace("\n", " ").split()).strip(" ,.;:")
    lowered = raw_text.lower()
    if lowered in {"none", "no", "not visible", "no visible", "absent"}:
        return "none", ""
    if lowered in {"uncertain", "unknown", "occluded", "cropped"}:
        return "uncertain", ""
    text = _clean_visual(raw_text)
    return ("visible", text) if text else ("missing", "")


def _remove_forbidden_limb_features(card: dict[str, Any], no_arms: bool, no_legs: bool) -> dict[str, Any]:
    cleaned = dict(card)
    cleaned["ears_arms"] = ""
    cleaned["limbs"] = ""

    forbidden = []
    if no_arms:
        forbidden.extend(["arm", "arms", "hand", "hands"])
    if no_legs:
        forbidden.extend(["leg", "legs", "foot", "feet", "standing", "upright"])
    if forbidden:
        pattern = re.compile(r"\b(?:" + "|".join(re.escape(word) for word in forbidden) + r")\b", re.IGNORECASE)
        for key in ("distinctive_features", "must_preserve", "sprite_notes"):
            cleaned[key] = [item for item in _list_text(cleaned.get(key)) if not pattern.search(item)]
    return cleaned


def build_cute_v3_prompt_pair_from_card(
    card: dict[str, Any],
    config_name: str | None = None,
) -> tuple[str, str, None]:
    """Cute-v2 rendering with source-authoritative appendage constraints."""
    del config_name
    arm_state, arm_text = _appendage_state(card.get("arms"))
    leg_state, leg_text = _appendage_state(card.get("legs"))
    structured = any(
        _clean_visual(_text(card.get(key)))
        for key in ("ears", "arms", "legs", "other_appendages")
    )

    prompt_card = _remove_forbidden_limb_features(
        card,
        no_arms=arm_state in {"none", "uncertain"},
        no_legs=leg_state in {"none", "uncertain"},
    ) if structured else card
    persona_en = build_text_character_visual_prompt(prompt_card)

    prompt_parts = [
        "monglestyle",
        "32-bit pixel art sprite",
        "hard pixel edges",
        "blocky pixel art",
    ]
    if persona_en:
        prompt_parts.append(persona_en)

    for key in ("ears", "other_appendages"):
        state, text = _appendage_state(card.get(key))
        if state == "visible":
            prompt_parts.append(text)
    if arm_state == "visible":
        prompt_parts.append(arm_text)
    elif arm_state in {"none", "uncertain"}:
        prompt_parts.append("no arms and no hands, do not invent side limbs")
    if leg_state == "visible":
        prompt_parts.append(leg_text)
    elif leg_state in {"none", "uncertain"}:
        prompt_parts.append("no legs and no feet, do not invent lower limbs")

    prompt_parts.extend(
        [
            "preserve only the appendages explicitly described from the source",
            "flat pixel shading",
            "limited color palette",
            "clean readable silhouette",
            "cute simple plush face matching the source expression",
            "single plush mascot sprite",
            "complete source silhouette",
            "centered",
            "source-matched pose and view",
            "pure white background",
        ]
    )
    return persona_en, ", ".join(prompt_parts), None


def build_prompt_pair(persona_en: str, config_name: str | None = None) -> tuple[str, str]:
    """Use the best previous structure: identity anchor first, details in both prompts."""
    parts = [part.strip() for part in persona_en.split(",") if part.strip()]
    prompt2_style_suffix = get_prompt2_style_suffix(config_name)
    if not parts:
        fallback = get_style_suffix(config_name)
        return fallback, fallback

    anchor = parts[0]
    skip_details = {
        "cute toy-like mascot",
        "simple cute expression",
        "clean readable silhouette",
    }
    detail_parts = [part for part in parts[1:] if part.lower() not in skip_details]
    details = ", ".join(detail_parts[:10])
    prompt_head = f"{anchor}, true 32-bit pixel art sprite, low resolution pixel art, crisp square pixels"
    prompt_tail = (
        "faithful to source mascot, preserve source shape colors face accessories, "
        "monglestyle, clean pixel outline, limited palette, simple pixel shading, "
        "single plush mascot sprite, complete source silhouette visible, centered, "
        "white background, no humanoid arms or legs"
    )
    prompt = f"{prompt_head}, {details}, {prompt_tail}" if details else f"{prompt_head}, {prompt_tail}"
    prompt_2_tail = "faithful to source mascot, preserve source shape colors face accessories"
    prompt_2 = (
        f"{anchor}, {prompt2_style_suffix}, {details}, {prompt_2_tail}"
        if details
        else f"{anchor}, {prompt2_style_suffix}, {prompt_2_tail}"
    )
    return prompt, prompt_2


def generate_text2img_character(
    pipe,
    prompt: str,
    prompt_2: str | None = None,
    steps: int = 8,
    guidance: float = 1.5,
    seed: int = 42,
):
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  generating pixel sprite (steps={steps}, guidance={guidance})...")
    return pipe(
        prompt=prompt,
        prompt_2=prompt_2,
        negative_prompt=TEXT2IMG_NEGATIVE,
        num_inference_steps=steps,
        guidance_scale=guidance,
        height=1024,
        width=1024,
        generator=torch.Generator(device=device).manual_seed(seed),
    ).images[0]


def generate_from_appearance(
    card_json_path: str,
    output_dir: str,
    seed: int = 42,
    configs: dict[str, dict[str, Any]] | None = None,
) -> list[Path]:
    from pipelines.text_character.pipeline import load_sdxl_pipeline, unload_sdxl_pipeline

    card = load_json(card_json_path)
    persona_en = build_text_character_visual_prompt(card)
    selected_configs = configs or TEXT2IMG_CONFIGS

    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "appearance_prompt.txt").write_text(persona_en, encoding="utf-8")
    (out_root / "input_card.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    outputs: list[Path] = []
    for name, config in selected_configs.items():
        run_seed = int(config.get("seed", seed))
        if seed is not None:
            run_seed = seed
        prompt, prompt_2 = build_prompt_pair(persona_en, config_name=name)
        (out_root / f"{name}_prompt.txt").write_text(prompt, encoding="utf-8")
        if prompt_2:
            (out_root / f"{name}_prompt_2.txt").write_text(prompt_2, encoding="utf-8")
        print(f"[{name}] lora={config['lora_scale']} steps={config['steps']} seed={run_seed}")
        pipe = load_sdxl_pipeline(lora_scale=float(config["lora_scale"]), lcm=bool(config.get("lcm", True)))
        try:
            result = generate_text2img_character(
                pipe,
                prompt,
                prompt_2=prompt_2,
                steps=int(config.get("steps", 8)),
                guidance=1.5 if config.get("lcm", True) else 7.5,
                seed=run_seed,
            )
        finally:
            unload_sdxl_pipeline(pipe)

        result_path = out_root / f"{name}.png"
        result.save(result_path)
        (out_root / f"{name}_params.json").write_text(
            json.dumps(
                {
                    "card_json_path": card_json_path,
                    "persona_en": persona_en,
                    "prompt": prompt,
                    "prompt_2": prompt_2,
                    "config": config,
                    "seed": run_seed,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        outputs.append(result_path)

    return outputs
