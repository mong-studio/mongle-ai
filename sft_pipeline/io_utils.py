"""sft_pipeline 공용 파일 I/O 헬퍼."""
from __future__ import annotations

import json
from pathlib import Path


def write_jsonl(samples: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
