from pathlib import Path
from llm_evaluation.langsmith.dataset import load_cases

_SEED = Path("llm_evaluation/langsmith/datasets/planner_cases.jsonl")


def test_load_cases_parses_seed():
    cases = load_cases(_SEED)
    assert len(cases) >= 5
    first = cases[0]
    assert set(first) >= {"inputs", "reference_outputs"}
    assert "turns" in first["inputs"]
    assert first["reference_outputs"]["expected_kind"] in {"candidates", "follow_up", "out_of_scope"}


def test_multiturn_case_present():
    cases = load_cases(_SEED)
    assert any(len(c["inputs"]["turns"]) >= 2 for c in cases)
