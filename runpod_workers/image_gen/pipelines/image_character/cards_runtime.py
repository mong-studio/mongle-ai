"""
Batch runner: real photos -> mascot image -> appearance card -> text2img character.

This is the batch version of run_appearance_text2img.py for a folder of photos.
It produces the same text2img-style outputs as:

  outputs/appearance_text2img/<name>/<item>/C_text_strong.png

Default input is the 25-photo test folder:

  ../mongle_32bit 2/image

Example:
  python run_photo_appearance_text2img_batch.py --name image25_compare_text --config C_text_strong
  python run_photo_appearance_text2img_batch.py --name image25_compare_text --config all --skip-existing
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT.parent
CHARACTER_PIPELINE_ROOT = WORKSPACE_ROOT / "mascot_character_pipeline"
MANUAL_OVERRIDE_DIR = ROOT / "outputs" / "appearance_text2img" / "manual_appearance_overrides"

for path in (WORKSPACE_ROOT, CHARACTER_PIPELINE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from .prompting import (
    TEXT2IMG_CONFIGS,
    build_cute_v2_prompt_pair_from_card,
    build_cute_v2_limb_safe_prompt_pair_from_card,
    build_cute_v3_prompt_pair_from_card,
    build_legacy_v2_exact_prompt_pair_from_card,
    build_prompt_pair_from_card,
    generate_text2img_character,
    load_json,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

SPECIFIC_ANIMAL_WORDS = {
    "cat",
    "dog",
    "bear",
    "monkey",
    "gorilla",
    "bird",
    "duck",
    "rabbit",
    "bunny",
    "dolphin",
    "whale",
    "orca",
    "shark",
    "seal",
    "squid",
    "octopus",
    "cuttlefish",
}

SEA_ANIMAL_WORDS = {"dolphin", "whale", "orca", "shark", "seal", "squid", "octopus", "cuttlefish"}

RISKY_OBJECT_WORDS = {
    "avocado",
    "banana",
    "eggplant",
    "bread",
    "bun",
    "cloud",
    "pillow",
    "pouch",
    "cushion",
    "blanket",
    "bee",
    "insect",
}

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


def _parse_only_items(value: str | None) -> set[str] | None:
    if not value:
        return None
    items: set[str] = set()
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        stem = Path(item).stem
        if stem.isdigit():
            stem = stem.zfill(2)
        items.add(stem.lower())
    return items


def list_images(image_dir: Path, limit: int | None = None, only: str | None = None) -> list[Path]:
    only_items = _parse_only_items(only)
    images = sorted(
        [path for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTS],
        key=lambda path: path.name.lower(),
    )
    if only_items is not None:
        images = [path for path in images if path.stem.lower() in only_items]
    return images[:limit] if limit is not None else images


def select_configs(config_name: str) -> dict[str, dict[str, Any]]:
    if config_name == "all":
        return TEXT2IMG_CONFIGS
    return {config_name: TEXT2IMG_CONFIGS[config_name]}


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _normalize_item_name(value: str) -> str:
    stem = Path(value).stem.strip()
    if stem.isdigit():
        stem = stem.zfill(2)
    return stem.lower()


def _unique(items: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        clean = _clean_text(item).strip(" ,.;:")
        if not clean:
            continue
        lowered = clean.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(clean)
        if len(result) >= limit:
            break
    return result


def _type_key(value: Any) -> str:
    return _clean_text(value).lower().replace("_", " ")


def _type_has_word(value: Any, words: set[str]) -> bool:
    type_text = _type_key(value)
    return any(re.search(rf"\b{re.escape(word)}\b", type_text) for word in words)


def _is_specific_animal_type(value: Any) -> bool:
    return _type_has_word(value, SPECIFIC_ANIMAL_WORDS)


def _is_sea_animal_type(value: Any) -> bool:
    return _type_has_word(value, SEA_ANIMAL_WORDS)


def _replace_risky_object_phrases(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    result = text
    for old, new in RISKY_OBJECT_PHRASES.items():
        result = re.sub(re.escape(old), new, result, flags=re.IGNORECASE)
    return _clean_text(result)


def _sanitize_generation_list(value: Any) -> list[str]:
    return _unique([_replace_risky_object_phrases(item) for item in _as_list(value)], limit=10)


def _is_generic_type(value: Any) -> bool:
    return _type_key(value) in {
        "",
        "soft object",
        "mascot",
        "character",
        "animal",
        "amphibian",
        "mammal",
        "creature",
        "cute animal",
        "plush animal",
        "abstract plush",
        "plush mascot",
        "animal-like plush",
        "object-shaped plush",
        "plush charm",
        "round food",
        "round_food",
        "food mascot",
        "round food mascot",
        "object mascot",
        "round object mascot",
    }


def _is_objectish_type(value: Any) -> bool:
    type_text = _type_key(value)
    object_words = {
        "star",
        "cloud",
        "food",
        "cutlet",
        "bread",
        "bun",
        "dumpling",
        "rice ball",
        "pillow",
        "pouch",
        "charm",
        "blanket",
        "cushion",
        "object",
        "avocado",
        "banana",
        "eggplant",
        "bee",
        "insect",
    }
    return any(word in type_text for word in object_words)


def _is_specific_type(value: Any) -> bool:
    return bool(_clean_text(value)) and not _is_generic_type(value)


def _is_type_supported_by_card(character_type: str, card: dict[str, Any]) -> bool:
    return True


def _choose_character_type(mascot_card: dict[str, Any], photo_card: dict[str, Any]) -> str:
    mascot_type = _clean_text(mascot_card.get("character_type"))
    photo_type = _clean_text(photo_card.get("character_type"))
    if _is_specific_type(photo_type) and _is_objectish_type(mascot_type) and not _is_objectish_type(photo_type):
        return photo_type
    if _is_specific_type(photo_type) and (_is_objectish_type(photo_type) or _is_generic_type(mascot_type)):
        return photo_type
    if _is_specific_type(mascot_type):
        return mascot_type
    return photo_type or mascot_type or "cute mascot"


def _identity_should_use_photo(mascot_card: dict[str, Any], photo_card: dict[str, Any]) -> bool:
    mascot_type = _clean_text(mascot_card.get("character_type"))
    photo_type = _clean_text(photo_card.get("character_type"))
    if not _is_specific_type(photo_type):
        return False
    if _is_specific_animal_type(photo_type) and not _is_specific_animal_type(mascot_type):
        return True
    if _is_generic_type(mascot_type):
        return True
    if _is_objectish_type(mascot_type) and not _is_objectish_type(photo_type):
        return True
    return (
        _is_objectish_type(photo_type)
        and _is_objectish_type(mascot_type)
        and _type_key(photo_type) != _type_key(mascot_type)
    )


def _choose_text(mascot_value: Any, photo_value: Any) -> str:
    mascot_text = _clean_text(mascot_value)
    photo_text = _clean_text(photo_value)
    if len(photo_text) > len(mascot_text):
        return photo_text
    return mascot_text or photo_text


def _outfit_primary_card(mascot_card: dict[str, Any], photo_card: dict[str, Any]) -> dict[str, Any]:
    """Pick one card to source must_preserve/sprite_notes/summary from.

    outfit/face/body/ears_arms already resolve per-field via _choose_text's
    longer-wins rule, so each is internally consistent on its own. But
    must_preserve/sprite_notes/character_summary used to concatenate both
    cards' lists, which silently reintroduced the losing card's feature
    words (e.g. "yellow shirt" alongside an outfit that already resolved to
    "orange blanket wrapped around the body") -- two different garments
    asserted at once in the same prompt. Following the same per-field
    winner for these fields keeps the merged card internally consistent.
    """
    mascot_text = _clean_text(mascot_card.get("outfit"))
    photo_text = _clean_text(photo_card.get("outfit"))
    return photo_card if len(photo_text) > len(mascot_text) else mascot_card


def merge_appearance_cards(mascot_card: dict[str, Any], photo_card: dict[str, Any]) -> dict[str, Any]:
    """Use mascot for simplified character form and photo for original details."""
    character_type = _choose_character_type(mascot_card, photo_card)
    object_type = _clean_text(photo_card.get("object_type")) or _clean_text(mascot_card.get("object_type")) or "soft object"
    identity_from_photo = _identity_should_use_photo(mascot_card, photo_card)
    primary_card = photo_card if identity_from_photo else _outfit_primary_card(mascot_card, photo_card)
    secondary_card = photo_card if primary_card is mascot_card else mascot_card
    main_color_cards = [photo_card] if identity_from_photo else [photo_card, mascot_card]

    return {
        "id": "runtime_hybrid",
        "object_type": object_type,
        "character_type": character_type,
        "character_summary": (
            _clean_text(primary_card.get("character_summary"))
            or _clean_text(secondary_card.get("character_summary"))
        ),
        "main_colors": _unique(
            [color for card in main_color_cards for color in _as_list(card.get("main_colors"))],
            limit=4,
        ),
        "secondary_colors": _unique(
            _as_list(photo_card.get("secondary_colors")) + _as_list(mascot_card.get("secondary_colors")),
            limit=6,
        ),
        "face": _clean_text(photo_card.get("face")) if identity_from_photo else _choose_text(mascot_card.get("face"), photo_card.get("face")),
        "body": _clean_text(photo_card.get("body")) if identity_from_photo else _choose_text(mascot_card.get("body"), photo_card.get("body")),
        "pose": _clean_text(photo_card.get("pose")) if identity_from_photo else (_clean_text(mascot_card.get("pose")) or _clean_text(photo_card.get("pose"))),
        "outfit": _choose_text(mascot_card.get("outfit"), photo_card.get("outfit")),
        "ears_arms": _clean_text(photo_card.get("ears_arms")) if identity_from_photo else _choose_text(mascot_card.get("ears_arms"), photo_card.get("ears_arms")),
        "ears": _clean_text(photo_card.get("ears")) or _clean_text(mascot_card.get("ears")),
        "arms": _clean_text(photo_card.get("arms")) or _clean_text(mascot_card.get("arms")),
        "legs": _clean_text(photo_card.get("legs")) or _clean_text(mascot_card.get("legs")),
        "other_appendages": _clean_text(photo_card.get("other_appendages")) or _clean_text(mascot_card.get("other_appendages")),
        "accessories": _unique(
            _as_list(photo_card.get("accessories")) + _as_list(mascot_card.get("accessories")),
            limit=5,
        ),
        "silhouette": _clean_text(photo_card.get("silhouette")) if identity_from_photo else _choose_text(mascot_card.get("silhouette"), photo_card.get("silhouette")),
        "must_preserve": _unique(_as_list(primary_card.get("must_preserve")), limit=10),
        "sprite_notes": _unique(_as_list(primary_card.get("sprite_notes")), limit=5),
    }


def normalize_generation_card(card: dict[str, Any]) -> dict[str, Any]:
    """Apply deterministic safety rules before building the final image prompt."""
    normalized = dict(card)

    object_type = _clean_text(normalized.get("object_type"))
    character_type = _clean_text(normalized.get("character_type"))

    if _is_generic_type(character_type) and _is_specific_animal_type(object_type):
        normalized["character_type"] = object_type
    elif _is_objectish_type(character_type) and _is_specific_animal_type(object_type):
        normalized["character_type"] = object_type
    elif _is_objectish_type(character_type):
        normalized["character_type"] = "abstract plush"

    for key in (
        "character_summary",
        "face",
        "body",
        "pose",
        "outfit",
        "ears_arms",
        "ears",
        "arms",
        "legs",
        "other_appendages",
        "silhouette",
    ):
        normalized[key] = _replace_risky_object_phrases(normalized.get(key))

    normalized["must_preserve"] = _sanitize_generation_list(normalized.get("must_preserve"))
    normalized["sprite_notes"] = _sanitize_generation_list(normalized.get("sprite_notes"))[:5]

    identity_text = " ".join(
        [
            _clean_text(normalized.get("character_type")),
            _clean_text(normalized.get("object_type")),
            _clean_text(normalized.get("character_summary")),
        ]
    )
    if _is_sea_animal_type(identity_text):
        ears_arms = _clean_text(normalized.get("ears_arms"))
        if re.search(r"\b(ear|ears|rabbit|bunny|arm|arms|hand|hands)\b", ears_arms, flags=re.IGNORECASE):
            normalized["ears_arms"] = "side fins, tail fin, and dorsal fin if visible"
        normalized["must_preserve"] = [
            item
            for item in _as_list(normalized.get("must_preserve"))
            if not re.search(r"\b(ear|ears|rabbit|bunny|arms|hands)\b", item, flags=re.IGNORECASE)
        ][:10]
        normalized["sprite_notes"] = [
            item
            for item in _as_list(normalized.get("sprite_notes"))
            if not re.search(r"\b(ear|ears|rabbit|bunny|arms|hands)\b", item, flags=re.IGNORECASE)
        ][:5]
        if not normalized["ears_arms"]:
            normalized["ears_arms"] = "fins and tail fin"

    return normalized


def apply_manual_appearance_override(card: dict[str, Any], item_name: str) -> dict[str, Any]:
    """Apply hand-restored cards for known VLM misses.

    These are intentionally data files, not hidden prompt hacks, so the
    restored identity can survive remerge/batch reruns.
    """
    override_path = MANUAL_OVERRIDE_DIR / f"{_normalize_item_name(item_name)}.json"
    if not override_path.exists():
        return card
    override = json.loads(override_path.read_text(encoding="utf-8"))
    merged = dict(card)
    merged.update(override)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image-dir",
        default=str(WORKSPACE_ROOT / "mongle_32bit 2" / "image"),
        help="Input photo folder. Default: ../mongle_32bit 2/image",
    )
    parser.add_argument(
        "--name",
        default="image25_photo_text",
        help="Output folder under outputs/appearance_text2img/",
    )
    parser.add_argument(
        "--config",
        choices=["all", *TEXT2IMG_CONFIGS.keys()],
        default="all",
        help="Which text2img config to run. Use C_text_strong for only the strong result.",
    )
    parser.add_argument(
        "--prompt-style",
        choices=["stable", "cute-v2", "cute-v2-limb-safe", "cute-v3", "legacy-v2-exact"],
        default="stable",
        help="Prompt structure used for text2img. Default keeps the existing stable style.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of photos to process")
    parser.add_argument("--only", default=None, help="Comma-separated item numbers/stems to process, e.g. 03,11,22")
    parser.add_argument(
        "--appearance-source",
        choices=["mascot", "photo", "hybrid"],
        default="mascot",
        help="Where to extract appearance from before text2img",
    )
    parser.add_argument("--skip-existing", action="store_true", help="Skip files that already exist")
    parser.add_argument("--no-4bit-vlm", action="store_true", help="Load the local VLM without 4bit quantization")
    parser.add_argument(
        "--mascot-strength",
        type=float,
        default=None,
        help="Optional Stage A denoise strength override for mascot generation",
    )
    args = parser.parse_args()

    image_dir = Path(args.image_dir).expanduser().resolve()
    if not image_dir.exists():
        raise FileNotFoundError(f"image dir not found: {image_dir}")

    images = list_images(image_dir, args.limit, args.only)
    if not images:
        raise FileNotFoundError(f"no images found in: {image_dir}")

    selected_configs = select_configs(args.config)
    out_root = ROOT / "outputs" / "appearance_text2img" / args.name
    out_root.mkdir(parents=True, exist_ok=True)
    summary_path = out_root / "summary.jsonl"

    print(f"input dir : {image_dir}")
    print(f"output dir: {out_root}")
    print(f"images    : {len(images)}")
    print(f"configs   : {', '.join(selected_configs)}")
    print(f"appearance: {args.appearance_source}")
    print(f"prompt    : {args.prompt_style}")
    print(f"seed      : {args.seed}")

    prompt_builders = {
        "stable": build_prompt_pair_from_card,
        "cute-v2": build_cute_v2_prompt_pair_from_card,
        "cute-v2-limb-safe": build_cute_v2_limb_safe_prompt_pair_from_card,
        "cute-v3": build_cute_v3_prompt_pair_from_card,
        "legacy-v2-exact": build_legacy_v2_exact_prompt_pair_from_card,
    }
    prompt_builder = prompt_builders[args.prompt_style]

    summary_file = summary_path.open("w", encoding="utf-8")
    try:
        # Step 1: real photos -> mascot.png. Load the heavy SDXL+ControlNet pipe once.
        print("\n=== [1] photo -> mascot.png ===")
        from mascot_character_pipeline.mascot_stage import (
            generate_mascot,
            load_mascot_pipeline,
            unload_mascot_pipeline,
        )

        mascot_pipe = load_mascot_pipeline()
        try:
            for index, image_path in enumerate(images, start=1):
                item_name = image_path.stem
                item_out_dir = out_root / item_name
                item_out_dir.mkdir(parents=True, exist_ok=True)
                mascot_path = item_out_dir / "mascot.png"
                (item_out_dir / "input_photo.txt").write_text(str(image_path), encoding="utf-8")

                if args.skip_existing and mascot_path.exists():
                    print(f"[{index}/{len(images)}] {item_name} skip mascot.png")
                    continue

                print(f"[{index}/{len(images)}] {image_path.name}")
                try:
                    mascot = generate_mascot(
                        str(image_path),
                        seed=args.seed,
                        pipe=mascot_pipe,
                        denoise_strength=args.mascot_strength,
                    )
                    mascot.save(mascot_path)
                except Exception as exc:
                    (item_out_dir / "error_mascot.txt").write_text(traceback.format_exc(), encoding="utf-8")
                    print(f"  failed mascot: {exc}")
        finally:
            unload_mascot_pipeline(mascot_pipe)

        # Step 2: image(s) -> appearance.json. Load the VLM once.
        print(f"\n=== [2] {args.appearance_source} -> appearance.json ===")
        from mascot_character_pipeline.appearance import (
            SOURCE_PHOTO_APPEARANCE_PROMPT,
            generate_card,
            load_model,
            unload_model,
        )

        vlm_model, vlm_processor = load_model(use_4bit=not args.no_4bit_vlm)
        cards: dict[str, dict[str, Any]] = {}
        try:
            for index, image_path in enumerate(images, start=1):
                item_name = image_path.stem
                item_out_dir = out_root / item_name
                mascot_path = item_out_dir / "mascot.png"
                card_path = item_out_dir / "appearance.json"

                if not mascot_path.exists():
                    print(f"[{index}/{len(images)}] {item_name} skip appearance; mascot.png missing")
                    continue

                if args.skip_existing and card_path.exists():
                    print(f"[{index}/{len(images)}] {item_name} skip appearance.json")
                    cards[item_name] = normalize_generation_card(load_json(card_path))
                    continue

                print(f"[{index}/{len(images)}] {item_name}")
                try:
                    mascot_card = None
                    photo_card = None
                    raw_parts: list[str] = []

                    if args.appearance_source in {"mascot", "hybrid"}:
                        with Image.open(mascot_path) as mascot_image:
                            mascot_card, mascot_raw = generate_card(
                                mascot_image.convert("RGB"),
                                vlm_model,
                                vlm_processor,
                            )
                        write_json(item_out_dir / "appearance_mascot.json", mascot_card)
                        (item_out_dir / "appearance_mascot_raw.txt").write_text(mascot_raw, encoding="utf-8")
                        raw_parts.append(f"=== mascot ===\n{mascot_raw}")

                    if args.appearance_source in {"photo", "hybrid"}:
                        with Image.open(image_path) as photo_image:
                            photo_card, photo_raw = generate_card(
                                photo_image.convert("RGB"),
                                vlm_model,
                                vlm_processor,
                                appearance_prompt=SOURCE_PHOTO_APPEARANCE_PROMPT,
                            )
                        write_json(item_out_dir / "appearance_photo.json", photo_card)
                        (item_out_dir / "appearance_photo_raw.txt").write_text(photo_raw, encoding="utf-8")
                        raw_parts.append(f"=== photo ===\n{photo_raw}")

                    if args.appearance_source == "hybrid":
                        if mascot_card is None or photo_card is None:
                            raise RuntimeError("hybrid appearance requires both mascot and photo cards")
                        card = merge_appearance_cards(mascot_card, photo_card)
                    elif args.appearance_source == "photo":
                        if photo_card is None:
                            raise RuntimeError("photo appearance was not generated")
                        card = photo_card
                    else:
                        if mascot_card is None:
                            raise RuntimeError("mascot appearance was not generated")
                        card = mascot_card

                    card = apply_manual_appearance_override(card, item_name)
                    card = normalize_generation_card(card)
                    write_json(card_path, card)
                    (item_out_dir / "appearance_raw.txt").write_text("\n\n".join(raw_parts), encoding="utf-8")
                    cards[item_name] = card
                except Exception as exc:
                    (item_out_dir / "error_appearance.txt").write_text(traceback.format_exc(), encoding="utf-8")
                    print(f"  failed appearance: {exc}")
        finally:
            unload_model(vlm_model, vlm_processor)

        if not cards:
            raise RuntimeError("No appearance cards were generated or loaded; cannot run text2img.")

        # Step 3: appearance.json -> A/B/C text2img outputs. Load one pipe per config.
        print("\n=== [3] appearance.json -> text2img png ===")
        from pipelines.text_character.pipeline import load_sdxl_pipeline, unload_sdxl_pipeline

        for config_name, config in selected_configs.items():
            print(f"\n--- config {config_name} (lora_scale={config['lora_scale']} steps={config['steps']}) ---")
            pipe = load_sdxl_pipeline(lora_scale=float(config["lora_scale"]), lcm=bool(config.get("lcm", True)))
            try:
                for index, item_name in enumerate(cards, start=1):
                    item_out_dir = out_root / item_name
                    result_path = item_out_dir / f"{config_name}.png"
                    row: dict[str, Any] = {
                        "item": item_name,
                        "config": config_name,
                        "appearance_source": args.appearance_source,
                        "prompt_style": args.prompt_style,
                        "seed": args.seed,
                        "ok": False,
                    }

                    if args.skip_existing and result_path.exists():
                        print(f"[{index}/{len(cards)}] {item_name} [{config_name}] skip png")
                        row["ok"] = True
                        row["skipped"] = True
                        row["result"] = str(result_path)
                    else:
                        print(f"[{index}/{len(cards)}] {item_name} [{config_name}]")
                        try:
                            card = cards[item_name]
                            persona_en, prompt, prompt_2 = prompt_builder(card, config_name=config_name)
                            result = generate_text2img_character(
                                pipe,
                                prompt,
                                prompt_2=prompt_2,
                                steps=int(config.get("steps", 8)),
                                guidance=1.5 if config.get("lcm", True) else 7.5,
                                seed=args.seed,
                            )

                            result.save(result_path)
                            (item_out_dir / "appearance_prompt.txt").write_text(persona_en, encoding="utf-8")
                            (item_out_dir / "final_prompt.txt").write_text(prompt, encoding="utf-8")
                            if prompt_2:
                                (item_out_dir / "final_prompt_2.txt").write_text(prompt_2, encoding="utf-8")
                            write_json(item_out_dir / "input_card.json", card)
                            write_json(
                                item_out_dir / f"{config_name}_params.json",
                                {
                                    "card_json_path": str(item_out_dir / "appearance.json"),
                                    "persona_en": persona_en,
                                    "prompt": prompt,
                                    "prompt_2": prompt_2,
                                    "config": config,
                                    "appearance_source": args.appearance_source,
                                    "prompt_style": args.prompt_style,
                                    "seed": args.seed,
                                },
                            )

                            row["ok"] = True
                            row["result"] = str(result_path)
                        except Exception as exc:
                            row["error"] = repr(exc)
                            (item_out_dir / f"error_{config_name}.txt").write_text(
                                traceback.format_exc(),
                                encoding="utf-8",
                            )
                            print(f"  failed text2img: {exc}")

                    summary_file.write(json.dumps(row, ensure_ascii=False) + "\n")
                    summary_file.flush()
            finally:
                unload_sdxl_pipeline(pipe)
    finally:
        summary_file.close()

    print(f"\nDone: {out_root}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
