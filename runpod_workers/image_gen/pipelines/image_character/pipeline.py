"""Production pipeline: one uploaded plush photo to one pixel-art image."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter
from typing import Any

from PIL import Image, ImageOps

from pipelines.shared.background import remove_solid_background
from .appearance import (
    SOURCE_PHOTO_APPEARANCE_PROMPT,
    generate_card,
    load_model,
    unload_model,
)
from .cards_runtime import merge_appearance_cards, normalize_generation_card
from .mascot_stage import generate_mascot, load_mascot_pipeline, unload_mascot_pipeline
from .models_runtime import load_text2img_pipeline, unload_pipeline
from .prompting import (
    TEXT2IMG_CONFIGS,
    build_cute_v2_limb_safe_prompt_pair_from_card,
    generate_text2img_character,
)


DEFAULT_CONFIG = TEXT2IMG_CONFIGS["A_text_soft"]
MAX_INPUT_PIXELS = int(os.environ.get("MAX_INPUT_PIXELS", "40000000"))


@dataclass(frozen=True)
class RuntimeInfo:
    model_mode: str
    gpu_name: str
    vram_gb: float


def _gpu_info() -> tuple[str, float]:
    import torch

    if not torch.cuda.is_available():
        return "none", 0.0
    props = torch.cuda.get_device_properties(0)
    return props.name, props.total_memory / (1024**3)


def _select_model_mode() -> RuntimeInfo:
    gpu_name, vram_gb = _gpu_info()
    requested = os.environ.get("MODEL_CACHE_MODE", "auto").strip().lower()
    if requested not in {"auto", "resident", "sequential"}:
        raise ValueError("MODEL_CACHE_MODE must be auto, resident, or sequential")
    mode = "resident" if requested == "resident" or (requested == "auto" and vram_gb >= 40) else "sequential"
    return RuntimeInfo(model_mode=mode, gpu_name=gpu_name, vram_gb=round(vram_gb, 1))


def normalize_input_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    if width < 64 or height < 64:
        raise ValueError("Input image must be at least 64x64 pixels")
    if width * height > MAX_INPUT_PIXELS:
        raise ValueError(f"Input image exceeds the {MAX_INPUT_PIXELS} pixel limit")
    return image.convert("RGB")


class PipelineRuntime:
    """Owns model lifecycle and serializes GPU inference per worker."""

    def __init__(self, model_mode: str | None = None) -> None:
        info = _select_model_mode()
        if model_mode is not None:
            if model_mode not in {"resident", "sequential"}:
                raise ValueError("model_mode must be resident or sequential")
            info = RuntimeInfo(model_mode=model_mode, gpu_name=info.gpu_name, vram_gb=info.vram_gb)
        self.info = info
        self._lock = threading.RLock()
        self._mascot_pipe = None
        self._vlm_model = None
        self._vlm_processor = None
        self._text_pipe = None

    def warmup(self) -> None:
        if self.info.model_mode != "resident":
            return
        with self._lock:
            if self._vlm_model is None:
                self._vlm_model, self._vlm_processor = load_model(use_4bit=True)
            if self._mascot_pipe is None:
                self._mascot_pipe = load_mascot_pipeline()
            if self._text_pipe is None:
                self._text_pipe = load_text2img_pipeline(lora_scale=float(DEFAULT_CONFIG["lora_scale"]))

    def close(self) -> None:
        with self._lock:
            if self._mascot_pipe is not None:
                unload_mascot_pipeline(self._mascot_pipe)
                self._mascot_pipe = None
            if self._vlm_model is not None:
                unload_model(self._vlm_model, self._vlm_processor)
                self._vlm_model = None
                self._vlm_processor = None
            if self._text_pipe is not None:
                unload_pipeline(self._text_pipe)
                self._text_pipe = None

    def _make_mascot(self, image: Image.Image, seed: int) -> Image.Image:
        owned = self.info.model_mode == "sequential"
        pipe = load_mascot_pipeline() if owned else self._mascot_pipe
        if pipe is None:
            raise RuntimeError("Mascot model is not initialized")
        try:
            with NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                image.save(tmp_path, format="PNG")
                return generate_mascot(str(tmp_path), seed=seed, pipe=pipe)
            finally:
                tmp_path.unlink(missing_ok=True)
        finally:
            if owned:
                unload_mascot_pipeline(pipe)

    def _extract_cards(self, image: Image.Image, mascot: Image.Image) -> tuple[dict[str, Any], dict[str, Any], str, str]:
        owned = self.info.model_mode == "sequential"
        if owned:
            model, processor = load_model(use_4bit=True)
        else:
            model, processor = self._vlm_model, self._vlm_processor
        if model is None or processor is None:
            raise RuntimeError("Appearance model is not initialized")
        try:
            mascot_card, mascot_raw = generate_card(mascot.convert("RGB"), model, processor)
            photo_card, photo_raw = generate_card(
                image.convert("RGB"),
                model,
                processor,
                appearance_prompt=SOURCE_PHOTO_APPEARANCE_PROMPT,
            )
            return mascot_card, photo_card, mascot_raw, photo_raw
        finally:
            if owned:
                unload_model(model, processor)

    def _generate(self, prompt: str, seed: int) -> Image.Image:
        owned = self.info.model_mode == "sequential"
        pipe = load_text2img_pipeline(lora_scale=float(DEFAULT_CONFIG["lora_scale"])) if owned else self._text_pipe
        if pipe is None:
            raise RuntimeError("Text-to-image model is not initialized")
        try:
            return generate_text2img_character(
                pipe,
                prompt,
                prompt_2=None,
                steps=int(DEFAULT_CONFIG["steps"]),
                guidance=1.5,
                seed=seed,
            )
        finally:
            if owned:
                unload_pipeline(pipe)

    def process(self, image: Image.Image, seed: int = 42, out_dir: str | Path | None = None) -> dict[str, Any]:
        image = normalize_input_image(image)
        seed = int(seed)
        output_dir = Path(out_dir) if out_dir is not None else None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            if self.info.model_mode == "resident":
                self.warmup()
            started = perf_counter()
            mascot = self._make_mascot(image, seed)
            mascot_card, photo_card, mascot_raw, photo_raw = self._extract_cards(image, mascot)
            appearance = normalize_generation_card(merge_appearance_cards(mascot_card, photo_card))
            persona_en, prompt, prompt_2 = build_cute_v2_limb_safe_prompt_pair_from_card(
                appearance,
                config_name="A_text_soft",
            )
            if prompt_2 is not None:
                raise RuntimeError("Production prompt must keep prompt_2 disabled")
            result_raw = self._generate(prompt, seed)
            result = remove_solid_background(result_raw)
            elapsed = round(perf_counter() - started, 3)

        metadata = {
            "seed": seed,
            "config": "A_text_soft",
            "prompt_style": "cute-v2-limb-safe",
            "background_removed": True,
            "model_mode": self.info.model_mode,
            "gpu_name": self.info.gpu_name,
            "vram_gb": self.info.vram_gb,
            "elapsed_seconds": elapsed,
        }
        if output_dir is not None:
            image.save(output_dir / "input.png")
            mascot.save(output_dir / "mascot.png")
            result_raw.save(output_dir / "result_raw.png")
            result.save(output_dir / "result.png")
            (output_dir / "appearance_mascot.json").write_text(json.dumps(mascot_card, ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "appearance_photo.json").write_text(json.dumps(photo_card, ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "appearance.json").write_text(json.dumps(appearance, ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "appearance_mascot_raw.txt").write_text(mascot_raw, encoding="utf-8")
            (output_dir / "appearance_photo_raw.txt").write_text(photo_raw, encoding="utf-8")
            (output_dir / "appearance_prompt.txt").write_text(persona_en, encoding="utf-8")
            (output_dir / "final_prompt.txt").write_text(prompt, encoding="utf-8")
            (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "image": result,
            "image_raw": result_raw,
            "mascot": mascot,
            "appearance": appearance,
            "appearance_mascot": mascot_card,
            "appearance_photo": photo_card,
            "persona_en": persona_en,
            "prompt": prompt,
            "metadata": metadata,
        }


_DEFAULT_RUNTIME: PipelineRuntime | None = None
_DEFAULT_RUNTIME_LOCK = threading.Lock()


def get_default_runtime() -> PipelineRuntime:
    global _DEFAULT_RUNTIME
    if _DEFAULT_RUNTIME is None:
        with _DEFAULT_RUNTIME_LOCK:
            if _DEFAULT_RUNTIME is None:
                _DEFAULT_RUNTIME = PipelineRuntime()
    return _DEFAULT_RUNTIME


def run_pipeline(
    image_pil: Image.Image,
    seed: int = 42,
    out_dir: str | Path | None = None,
    runtime: PipelineRuntime | None = None,
) -> dict[str, Any]:
    return (runtime or get_default_runtime()).process(image_pil, seed=seed, out_dir=out_dir)
