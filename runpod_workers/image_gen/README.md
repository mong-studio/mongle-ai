# Image Generation RunPod Worker

This is the production RunPod Serverless worker for Mongle image generation.
It owns GPU inference only; FastAPI orchestration remains in `agents/` and
RunPod transport remains in `adapters/character_creation/runpod_image.py`.

## Layout

```text
image_gen/
├── handler.py              # Serverless entry point and mode router
├── Dockerfile
├── requirements.txt        # Single dependency source for the worker image
└── pipelines/
    ├── image_character/    # Photo -> transparent character PNG + appearance
    ├── text_character/     # Persona text -> transparent PNG + appearance
    ├── feed/               # Appearance + quest -> feed image
    └── shared/             # Canonical appearance and background utilities
```

## What This Worker Does

One RunPod Serverless handler dispatches three modes:

```json
{"input": {"mode": "image_character", "image": "<base64>", "seed": 42}}
```

```json
{"input": {"mode": "text_character", "persona": "노란 오리 인형", "seed": 42}}
```

```json
{
  "input": {
    "mode": "feed",
    "appearance": {"character_type": "duck", "main_colors": ["yellow"]},
    "quest_ko": "공원에서 30분 산책을 완료했어",
    "seed": 42
  }
}
```

Character modes return:

```json
{
  "status": "done",
  "mode": "image_character|text_character",
  "image": "<base64 transparent PNG>",
  "appearance": {"...": "..."},
  "width": 1024,
  "height": 1024,
  "seed": 42
}
```

Feed mode returns:

```json
{
  "status": "done",
  "mode": "feed",
  "image": "<base64 PNG>",
  "appearance": {"...": "..."},
  "quest_ko": "...",
  "quest_en": "...",
  "width": 1024,
  "height": 1024,
  "seed": 42
}
```

## Important RunPod Environment

```text
MASCOT_LORA_SOURCE=Hadimeeee/mongle-mascot-lora
CHAR_LORA_SOURCE=Hadimeeee/mongle-character-lora
LCM_LORA_SOURCE=latent-consistency/lcm-lora-sdxl
HF_HOME=/runpod-volume/huggingface
```

If any Hugging Face repos are private, also set:

```text
HF_TOKEN=<token>
```

## API Contract

The worker uses one canonical contract:

```text
character image/text -> transparent PNG + canonical appearance JSON
appearance JSON + quest -> feed PNG
```

`handler.py` accepts the compatibility aliases documented in `MODE_ALIASES`,
but new callers should send `image_character`, `text_character`, or `feed`.

GitHub Actions builds this directory through `.github/workflows/deploy-workers.yml`.
