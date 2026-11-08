"""Check the semantic layer against the database (Step 24; run in CI after the seed).

    python -m scripts.schema_check

Owner check of every table, column and metric definition of config/semantic. Exit 1 on
any problem, for example a renamed or dropped column.
"""

import sys

import psycopg

from app.core.config import get_settings
from app.semantic.catalog import load_semantic_layer_file
from app.semantic.schema_check import check_semantic_schema


def main() -> int:
    layer = load_semantic_layer_file()
    with psycopg.connect(get_settings().owner_conninfo()) as conn:
        problems = check_semantic_schema(conn, layer)
    if problems:
        print("Schema drift: the semantic layer does not match the database:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"Schema check passed: {len(layer.tables)} tables, {len(layer.metrics)} metrics.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
