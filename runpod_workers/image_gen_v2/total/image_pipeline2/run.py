"""Local CLI for image_pipeline2."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from .pipeline import PipelineRuntime


def main() -> None:
    parser = argparse.ArgumentParser(description="Plush photo to pixel-art character")
    parser.add_argument("--image", required=True, help="Input JPG/PNG path")
    parser.add_argument("--name", default="output", help="Folder name under outputs/image_pipeline2")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model-mode", choices=["resident", "sequential"], default=None)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    out_dir = root / "outputs" / "image_pipeline2" / args.name
    runtime = PipelineRuntime(model_mode=args.model_mode)
    try:
        with Image.open(args.image) as source:
            result = runtime.process(source, seed=args.seed, out_dir=out_dir)
    finally:
        runtime.close()

    print(f"result: {out_dir / 'result.png'}")
    print(f"mode: {result['metadata']['model_mode']}")
    print(f"elapsed: {result['metadata']['elapsed_seconds']}s")


if __name__ == "__main__":
    main()
