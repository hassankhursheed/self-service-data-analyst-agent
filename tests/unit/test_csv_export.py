"""Step 26 extra: CSV download of a result."""

import csv
import datetime as dt
import io
from decimal import Decimal

from app.agent.csv_export import csv_cell, result_csv


def test_values_are_written_plainly() -> None:
    assert csv_cell(None) == ""
    assert csv_cell(Decimal("81234.50")) == "81234.50"
    assert csv_cell(-12) == "-12"  # negative numbers are not treated as formulas
    assert csv_cell(dt.date(2025, 3, 31)) == "2025-03-31"
    assert csv_cell(True) == "true"


def test_formula_like_text_cannot_run_in_a_spreadsheet() -> None:
    for text in ("=HYPERLINK(1)", "+1", "-1+2", "@SUM(A1)", "\tx", "\rx"):
        assert csv_cell(text).startswith("'")
    assert csv_cell("Berglunds snabbköp") == "Berglunds snabbköp"


def test_result_csv_has_a_header_and_quotes_commas() -> None:
    text = result_csv(["company", "revenue"], [("Ernst, Handel", Decimal("1.5")), ("A", None)])
    assert list(csv.reader(io.StringIO(text))) == [
        ["company", "revenue"],
        ["Ernst, Handel", "1.5"],
        ["A", ""],
    ]
