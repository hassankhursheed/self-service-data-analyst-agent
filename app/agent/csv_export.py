"""CSV download of a result (recommended extra, brief §17).

The file holds exactly the rows the user's table shows (already limited to their role
and region). Cells that a spreadsheet would read as a formula (starting with ``=``, ``+``,
``-``, ``@``, tab or carriage return) get a leading apostrophe, so opening the file can
never run anything.
"""

import csv
import datetime as dt
import io
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: Any) -> str:  # noqa: ANN401 (result cells have any SQL type)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | Decimal):
        return str(value)  # numbers stay numbers, negative ones included
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    text = str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def result_csv(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([csv_cell(c) for c in columns])
    writer.writerows([csv_cell(v) for v in row] for row in rows)
    return buffer.getvalue()
