from pathlib import Path
from llm_evaluation.langsmith.dataset import load_cases

_SEED = Path("llm_evaluation/langsmith/datasets/planner_cases.jsonl")


def test_load_cases_parses_seed():
    cases = load_cases(_SEED)
    assert len(cases) >= 15
    first = cases[0]
    assert set(first) >= {"inputs", "reference_outputs"}
    assert "turns" in first["inputs"]
    assert first["reference_outputs"]["expected_kind"] in {"candidates", "follow_up", "out_of_scope"}


def test_all_expected_kinds_covered():
    cases = load_cases(_SEED)
    kinds = {c["reference_outputs"]["expected_kind"] for c in cases}
    assert kinds == {"candidates", "follow_up", "out_of_scope"}


def test_user_ids_unique():
    cases = load_cases(_SEED)
    ids = [c["inputs"]["user_id"] for c in cases]
    assert len(ids) == len(set(ids))


def test_multiturn_case_present():
    cases = load_cases(_SEED)
    assert any(len(c["inputs"]["turns"]) >= 2 for c in cases)
