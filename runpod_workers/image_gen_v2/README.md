# image_gen_v2 RunPod Worker Draft

This is a safe draft worker for migrating Mongle image generation to the latest
`image_test_ver/total` pipelines.

It is intentionally separate from the existing `mongle-ai/runpod_workers/image_gen`
worker. Do not replace the production endpoint until this worker is tested
directly on RunPod.

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

## Why This Exists

The current production worker uses:

```json
{"input": {"adapter": "character|bg|feed", "source_image_b64": "..."}}
```

The new `total` pipeline uses:

```text
character image/text -> transparent PNG + canonical appearance JSON
appearance JSON + quest -> feed PNG
```

So FastAPI and agents should be changed only after this worker passes direct
RunPod tests.
