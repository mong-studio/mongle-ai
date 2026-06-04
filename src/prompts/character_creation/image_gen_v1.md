# Image Generator Style Guard v1

> ⚠ 런타임 단일 소스(SSOT)는 `adapters/character_creation/lora_image.py` 의
> `_PROMPT` / `_NEGATIVE_PROMPT` 상수다. 본 문서는 그 프롬프트를 사람이 읽기 위한
> 카탈로그이며, 코드와 항상 일치시켜야 한다(AI_RULES §5). 둘이 어긋나면 코드를 기준으로 본다.

파이프라인: `StableDiffusionXLControlNetImg2ImgPipeline` (SDXL base 1.0 + canny ControlNet) + LoRA + rembg 배경 제거.

## Positive prompt

```
16x16 pixel art sprite, NES style, cute stuffed animal character,
strictly pixelated, chunky visible pixels, limited flat color palette,
sharp pixel boundaries, no anti-aliasing, no gradients, no shading,
indie RPG game sprite style, warm saturated color palette,
chibi proportions, thick dark outlines, flat 2-tone coloring,
white background, full body, front-facing,
bold black outlines, clean pixel edges
```

## Negative prompt

```
realistic, 3d render, blurry, smooth, photograph, gradient, shadow,
anti-aliasing, soft edges, painterly, watercolor, sketch, detailed texture
```

## Inference settings

| 항목 | 값 |
|---|---|
| size | 512 x 512 |
| num_inference_steps | 30 |
| guidance_scale | 7.5 |
| strength | 0.6 (사진 있을 때) / 0.99 (기본 실루엣) |
| controlnet_conditioning_scale | 0.8 (사진 있을 때) / 0.4 (기본 실루엣) |
