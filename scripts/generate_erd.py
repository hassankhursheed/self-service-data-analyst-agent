"""Regenerate the Mermaid ERD in docs/design/database-design.md from the SQLAlchemy models.

Usage: python scripts/generate_erd.py
The ERD sits between the ``<!-- erd:start -->`` and ``<!-- erd:end -->`` markers.
"""

import sys

from app.core.config import PROJECT_ROOT
from app.db.erd import render_erd

DOC = PROJECT_ROOT / "docs" / "design" / "database-design.md"
START, END = "<!-- erd:start -->", "<!-- erd:end -->"


def main() -> int:
    text = DOC.read_text("utf-8")
    if START not in text or END not in text:
        print(f"ERD markers not found in {DOC}", file=sys.stderr)
        return 1
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    DOC.write_text(f"{before}{START}\n```mermaid\n{render_erd()}```\n{END}{after}", "utf-8")
    print(f"Updated ERD in {DOC.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
