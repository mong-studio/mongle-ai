"""Canonical character profile matching image_pipeline2 appearance.json."""

from __future__ import annotations

from typing import Any


PROFILE_KEYS = (
    "id",
    "object_type",
    "character_type",
    "character_summary",
    "main_colors",
    "secondary_colors",
    "face",
    "body",
    "pose",
    "outfit",
    "ears_arms",
    "accessories",
    "silhouette",
    "must_preserve",
    "sprite_notes",
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    text = _text(value)
    if not text or text.lower() in {"none", "not visible", "n/a"}:
        return []
    return [text]


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise ValueError("appearance must be a JSON object")

    normalized = {
        "id": _text(profile.get("id")) or "runtime",
        "object_type": _text(profile.get("object_type")) or "soft object",
        "character_type": _text(profile.get("character_type")) or "plush mascot",
        "character_summary": _text(profile.get("character_summary")),
        "main_colors": _list(profile.get("main_colors"))[:4],
        "secondary_colors": _list(profile.get("secondary_colors"))[:6],
        "face": _text(profile.get("face")),
        "body": _text(profile.get("body")),
        "pose": _text(profile.get("pose")),
        "outfit": _text(profile.get("outfit")),
        "ears_arms": _text(profile.get("ears_arms")),
        "accessories": _list(profile.get("accessories"))[:5],
        "silhouette": _text(profile.get("silhouette")),
        "must_preserve": _list(profile.get("must_preserve"))[:10],
        "sprite_notes": _list(profile.get("sprite_notes"))[:5],
    }
    return normalized


def from_text_appearance(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert text_pipeline's generated-image analysis to the image schema."""
    animal = _text(raw.get("animal_type")) or "plush mascot"
    body_color = _text(raw.get("body_color"))
    secondary = _list(raw.get("secondary_colors"))
    body_shape = _text(raw.get("body_shape"))
    eye_style = _text(raw.get("eye_style"))
    nose_mouth = _text(raw.get("nose_mouth"))
    ear_shape = _text(raw.get("ear_shape"))
    accessories = _list(raw.get("accessories"))
    features = _list(raw.get("distinctive_features"))
    has_limbs = _text(raw.get("has_limbs")).lower()
    overall = _text(raw.get("overall_feel"))

    face = ", ".join(part for part in (eye_style, nose_mouth) if part)
    ears_arms_parts = []
    if ear_shape and ear_shape.lower() not in {"none", "not visible"}:
        ears_arms_parts.append(ear_shape)
    if has_limbs == "yes":
        ears_arms_parts.append("visible plush limbs")

    must_preserve = []
    if body_color:
        must_preserve.append(f"{body_color} body")
    must_preserve.extend(secondary[:3])
    must_preserve.extend(features[:6])

    summary_parts = [body_color, animal, body_shape, overall]
    return normalize_profile(
        {
            "id": "runtime_text",
            "object_type": "pixel mascot",
            "character_type": animal,
            "character_summary": " ".join(part for part in summary_parts if part),
            "main_colors": [body_color] if body_color else [],
            "secondary_colors": secondary,
            "face": face,
            "body": body_shape,
            "pose": "front-facing centered pose",
            "outfit": "",
            "ears_arms": ", ".join(ears_arms_parts),
            "accessories": accessories,
            "silhouette": body_shape,
            "must_preserve": must_preserve,
            "sprite_notes": ["preserve the generated character identity"],
        }
    )
