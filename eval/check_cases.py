"""Check the evaluation cases before they are used (Step 22, docs/evaluation.md).

    python -m eval.check_cases            # check only
    python -m eval.check_cases --write    # also save eval/expected/v<version>.json

For every case it:
1. validates expected_sql with the SQL validator for the case's test user;
2. runs expected_sql once as that user through the read-only role (same secure views and
   region rules as the agent) and reports the row count and first row;
3. runs truth_sql / leak_sql as the database owner (access-control cases);
4. reports eval questions that are very similar to an enabled verified example the user
   may use (so the "with verified examples" experiment is not inflated by duplicates).

Exit code 1 when any SQL is invalid or fails.
"""

import asyncio
import datetime as dt
import sys

import psycopg

from app.auth.models import AuthenticatedUser
from app.core.config import get_settings
from app.core.context import UserContext
from app.core.enums import RoleName
from app.db.analytics import run_readonly
from app.db.session import create_analytics_engine
from app.eval.cases import EvalCaseFile, load_cases
from app.eval.expected import CaseExpectation, ExpectedFile, result_set, save_expected
from app.safety.sql_validator import validate
from app.semantic.catalog import load_active_semantic_layer
from app.semantic.verified import load_active_examples, similarity

OVERLAP_WARNING = 0.8


def load_users(conn: psycopg.Connection) -> dict[str, AuthenticatedUser]:
    rows = conn.execute(
        "SELECT u.id, u.username, r.name, ur.region_code FROM app.users u "
        "LEFT JOIN app.user_roles uro ON uro.user_id = u.id "
        "LEFT JOIN app.roles r ON r.id = uro.role_id "
        "LEFT JOIN app.user_regions ur ON ur.user_id = u.id"
    ).fetchall()
    return {
        username: AuthenticatedUser(
            user_id=uid, username=username, role=RoleName(role) if role else None, region=region
        )
        for uid, username, role, region in rows
    }


def short(row: object) -> str:
    text = repr(row)
    return text if len(text) <= 90 else text[:87] + "..."


async def check(cases: EvalCaseFile, write: bool = False) -> int:
    settings = get_settings()
    engine = create_analytics_engine(settings)
    problems = 0
    expectations: dict[str, CaseExpectation] = {}
    with psycopg.connect(settings.owner_conninfo(), autocommit=True) as conn:
        users = load_users(conn)
        layer = load_active_semantic_layer(conn)
        library = load_active_examples(conn)
        for case in cases.cases:
            user = users.get(case.test_user)
            if user is None:
                print(f"{case.id}  ERROR  unknown test user {case.test_user}")
                problems += 1
                continue
            line = f"{case.id}  {case.type.value:<14} {case.test_user:<15}"
            found: dict[str, object] = {}
            if case.expected_sql:
                if user.role is None:
                    print(f"{line} ERROR  a case with SQL needs a user with a role")
                    problems += 1
                    continue
                result = validate(case.expected_sql, user.role, layer)
                if not result.allowed:
                    print(f"{line} INVALID {result.reason_code} {result.detail}")
                    problems += 1
                    continue
                try:
                    ctx = UserContext(username=user.username, role=user.role, region=user.region)
                    out = await run_readonly(
                        result.final_sql or case.expected_sql, ctx, 10_000, 1000, engine=engine
                    )
                except Exception as exc:  # report every failing case, then exit 1
                    print(f"{line} FAILED  {exc}")
                    problems += 1
                    continue
                found["expected"] = result_set(out.columns, out.rows)
                first = out.rows[0] if out.rows else None
                print(f"{line} ok  {out.row_count:>4} rows  {short(first)}")
            for label, sql in (("truth", case.truth_sql), ("leak", case.leak_sql)):
                if sql:
                    cursor = conn.execute(sql)
                    rows = cursor.fetchall()
                    columns = [d.name for d in cursor.description or []]
                    found[label] = result_set(columns, rows)
                    print(
                        f"{line} {label:<5} {len(rows):>4} rows  {short(rows[0] if rows else None)}"
                    )
            expectations[case.id] = CaseExpectation.model_validate(found)
            if not case.expected_sql and not case.truth_sql and not case.leak_sql:
                print(f"{line} ({case.expected_behaviour.value}, no SQL)")
            if user.role is not None:
                for example in library:
                    if user.role in example.allowed_roles:
                        score = similarity(case.question, example)
                        if score >= OVERLAP_WARNING:
                            print(
                                f"      overlap {score:.2f} with verified example: "
                                f"{example.question!r}"
                            )
    await engine.dispose()
    if write and not problems:
        path = save_expected(
            ExpectedFile(
                cases_version=cases.version,
                generated_at=dt.datetime.now(dt.UTC),
                cases=expectations,
            )
        )
        print(f"\nwrote {path}")
    return problems


def main() -> int:
    cases = load_cases()
    print(f"eval/cases.yaml version {cases.version}: {len(cases.cases)} cases")
    write = "--write" in sys.argv[1:]
    problems = asyncio.run(check(cases, write), loop_factory=asyncio.SelectorEventLoop)
    print(f"\n{problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
