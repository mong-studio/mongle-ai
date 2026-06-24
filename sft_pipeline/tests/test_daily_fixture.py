"""I1 guard: raw_daily.csv fixture rows must be clean after structure_daily_row,
and build_daily_days titles must contain no filler chores."""
import csv
from datetime import date
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "raw_daily.csv"
TODAY = date(2026, 6, 24)

_FILLER_WORDS = ("확인", "점검", "정리")


def _read_fixture() -> list[dict]:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _structured_rows() -> list[dict]:
    """Return structured dicts (as written by write_structured_daily) for all fixture rows."""
    from sft_pipeline.structure.daily_fields import structure_daily_row
    from sft_pipeline.structure.run_daily_structure import _to_record

    rows = _read_fixture()
    return [_to_record(structure_daily_row(r)) for r in rows]


@pytest.mark.parametrize("row", _read_fixture())
def test_fixture_row_has_no_review_flags(row):
    """After structure_daily_row, every fixture row must yield review_flags == []."""
    from sft_pipeline.structure.daily_fields import structure_daily_row

    result = structure_daily_row(row)
    assert result.review_flags == [], (
        f"Fixture row {row.get('source_url')!r} produced review_flags={result.review_flags}"
    )


@pytest.mark.parametrize("structured", _structured_rows())
def test_fixture_build_daily_days_no_filler(structured):
    """build_daily_days titles must contain no 확인/점검/정리 filler words."""
    from sft_pipeline.build.lib.daily_nodes_template import build_daily_days

    days = build_daily_days(structured, TODAY)
    titles = [t["title"] for d in days for t in d["tasks"]]
    assert titles, f"No tasks generated for {structured.get('source_url')!r}"
    for title in titles:
        for filler in _FILLER_WORDS:
            assert filler not in title, (
                f"Filler word {filler!r} found in title {title!r} "
                f"for {structured.get('source_url')!r}"
            )
