"""CLI for generating feed images from canonical appearance JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


PIPELINES_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PIPELINES_ROOT.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

OUTPUT_ROOT = PIPELINES_ROOT / "outputs" / "feed"


def parse_args():
    parser = argparse.ArgumentParser(description="Generate feed images from appearance JSON")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--appearance", help="Path to one canonical appearance.json")
    source.add_argument("--cases", help="Path to a batch cases JSON file")
    parser.add_argument("--quest", help="Korean quest text for --appearance mode")
    parser.add_argument("--name", default="run_01", help="Output folder name")
    parser.add_argument("--seed", type=int, default=123)
    return parser.parse_args()


def _read_profile(value):
    if isinstance(value, dict):
        return value
    with Path(value).open(encoding="utf-8") as profile_file:
        return json.load(profile_file)


def load_cases(args) -> list[dict]:
    if args.appearance:
        if not args.quest:
            raise ValueError("--quest is required with --appearance")
        appearance_path = Path(args.appearance)
        return [{
            "name": appearance_path.parent.name,
            "appearance": _read_profile(appearance_path),
            "quest_ko": args.quest,
        }]

    with Path(args.cases).open(encoding="utf-8") as cases_file:
        cases = json.load(cases_file)
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty JSON array")
    for case in cases:
        if not all(key in case for key in ("name", "appearance", "quest_ko")):
            raise ValueError("each case requires name, appearance, and quest_ko")
        case["appearance"] = _read_profile(case["appearance"])
    return cases


def run_translation_worker(batch: list[dict], work_dir: Path) -> list[dict]:
    """Translate quests in a subprocess so its VLM memory is fully released."""
    batch_path = work_dir / "_translation_batch.json"
    batch_path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "pipelines.feed.vlm_worker", str(batch_path)],
        cwd=str(WORKSPACE_ROOT),
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"quest translation failed with exit code {proc.returncode}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main():
    args = parse_args()
    cases = load_cases(args)
    out_dir = OUTPUT_ROOT / args.name
    out_dir.mkdir(parents=True, exist_ok=True)

    for case in cases:
        case["out_dir"] = out_dir / str(case["name"])
        case["out_dir"].mkdir(parents=True, exist_ok=True)

    translation_batch = [
        {"name": case["name"], "quest_ko": case["quest_ko"]}
        for case in cases
    ]
    translated = {
        item["name"]: item["quest_en"]
        for item in run_translation_worker(translation_batch, out_dir)
    }

    from pipelines.shared.character_profile import normalize_profile
    from .pipeline import generate, load_pipeline, unload_pipeline

    pipe = load_pipeline()
    try:
        for index, case in enumerate(cases):
            profile = normalize_profile(case["appearance"])
            quest_en = translated[case["name"]]
            image = generate(profile, quest_en, pipe, seed=args.seed + index)
            image.save(case["out_dir"] / "feed.png")
            (case["out_dir"] / "appearance.json").write_text(
                json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (case["out_dir"] / "quest.json").write_text(
                json.dumps(
                    {"quest_ko": case["quest_ko"], "quest_en": quest_en},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"[{case['name']}] {case['out_dir'] / 'feed.png'}")
    finally:
        unload_pipeline(pipe)


if __name__ == "__main__":
    main()
