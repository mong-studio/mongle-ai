import json

from sft_pipeline.experiments.planner_sft_v3.build_ab_notebook import build_notebook


def test_notebook_structure(tmp_path):
    out = tmp_path / "ab_test.ipynb"
    build_notebook(out)
    nb = json.loads(out.read_text(encoding="utf-8"))
    sources = "".join("".join(c["source"]) for c in nb["cells"])
    # base 와 adapter 양쪽 실행 + 판정 셀이 있어야 함
    assert '"base"' in sources
    assert "score_outputs" in sources and "passes_gate" in sources
    assert "semantic_avg" in sources  # LoRA ≥ base 판정 (스펙 §7)
    assert nb["nbformat"] == 4
