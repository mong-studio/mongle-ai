"""Example app-server client for a deployed RunPod Serverless endpoint."""

from __future__ import annotations

import argparse
import base64
import io
import os
from pathlib import Path

import runpod
from PIL import Image, ImageOps


def encode_upload(path: str, max_side: int = 2048, quality: int = 90) -> str:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", default="result.png")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    runpod.api_key = os.environ["RUNPOD_API_KEY"]
    endpoint = runpod.Endpoint(os.environ["RUNPOD_ENDPOINT_ID"])
    job = endpoint.run({"image": encode_upload(args.image), "seed": args.seed})
    result = job.output(timeout=900)
    if result.get("status") != "done":
        raise RuntimeError(result)
    Path(args.output).write_bytes(base64.b64decode(result["image"]))
    print(args.output)


if __name__ == "__main__":
    main()
