from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_SEED = Path(__file__).parent / "datasets" / "planner_cases.jsonl"


def load_cases(path: str | Path | None = None) -> list[dict]:
    """jsonl 시드를 파싱해 example dict 리스트로 반환."""
    p = Path(path) if path else _DEFAULT_SEED
    cases: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def ensure_dataset(client, name: str, cases_path: str | Path | None = None) -> str:
    """LangSmith 데이터셋을 멱등 생성하고 example을 채운다. dataset id 반환.

    이미 있으면 재사용하고, 아직 없는 (inputs) 조합만 추가한다.
    """
    cases = load_cases(cases_path)
    if client.has_dataset(dataset_name=name):
        ds = client.read_dataset(dataset_name=name)
    else:
        ds = client.create_dataset(dataset_name=name)

    existing = {
        json.dumps(ex.inputs, sort_keys=True, ensure_ascii=False)
        for ex in client.list_examples(dataset_id=ds.id)
    }
    to_add = [
        c for c in cases
        if json.dumps(c["inputs"], sort_keys=True, ensure_ascii=False) not in existing
    ]
    if to_add:
        client.create_examples(
            dataset_id=ds.id,
            inputs=[c["inputs"] for c in to_add],
            outputs=[c.get("reference_outputs") for c in to_add],
            metadata=[c.get("metadata") for c in to_add],
        )
    return str(ds.id)
