"""CLI for text-to-character generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


TOTAL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = TOTAL_ROOT.parent
sys.path.insert(0, str(WORKSPACE_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a pixel character from Korean text")
    parser.add_argument("--persona", required=True)
    parser.add_argument("--name", default="output")
    parser.add_argument("--lcm", action="store_true", default=True)
    parser.add_argument("--no-lcm", dest="lcm", action="store_false")
    parser.add_argument("--lora-scale", type=float, default=0.9)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    from .pipeline import run_pipeline

    out_dir = TOTAL_ROOT / "outputs" / "text_pipeline" / args.name
    result = run_pipeline(
        persona_ko=args.persona,
        lcm=args.lcm,
        lora_scale=args.lora_scale,
        steps=args.steps,
        seed=args.seed,
        out_dir=str(out_dir),
    )
    print(f"result: {out_dir / 'result_nobg.png'}")
    print(f"character_type: {result['appearance']['character_type']}")
    print(f"main_colors: {result['appearance']['main_colors']}")


if __name__ == "__main__":
    main()
