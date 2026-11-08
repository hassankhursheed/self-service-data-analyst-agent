"""Verified query library: seeded examples, loading and similarity search (brief §16).

Verified examples are questions with SQL that a person checked. N-05 picks the most similar
enabled examples that the user's role may use and N-06 shows them to the model as
few-shot guidance. They never bypass anything: every example is re-checked with the SQL
validator for the user's role before it is offered, and the generated SQL is validated and
executed under the user's role and region as usual.

Similarity is keyword-based (token overlap, cosine over token sets), like the semantic
retriever: the library is small (tens of examples), fully explainable and needs no
embedding model or extra service. See docs/verified-queries.md.
"""

import asyncio
import math
import uuid
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import PROJECT_ROOT
from app.core.enums import RoleName
from app.core.yaml_config import load_yaml_model
from app.db.pools import lookup_pool
from app.safety.sql_policy import SqlPolicy
from app.safety.sql_validator import validate
from app.semantic.models import SemanticLayer
from app.semantic.retriever import tokenize

VERIFIED_QUERIES_FILE = PROJECT_ROOT / "config" / "verified_queries.yaml"
# Stable lineage IDs for seeded examples: uuid5(namespace, key).
SEED_NAMESPACE = uuid.UUID("6b1f5c7e-2a7d-4f6e-9a51-3c0f1e2d4b80")

# Words that say nothing about which query fits.
STOPWORDS = frozenset(
    """a an and are as at be by did do does for from give how i in is it me much many of on
    or our show tell that the their them there these this to was we were what which who with
    each per all""".split()  # noqa: SIM905 (one readable block of words)
)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SeedExample(_Frozen):
    key: str = Field(pattern=r"^[a-z0-9-]{3,64}$")
    question: str = Field(min_length=3)
    description: str = Field(min_length=3)
    sql: str = Field(min_length=10)
    metrics: list[str] = []
    allowed_roles: list[RoleName] = Field(min_length=1)


class SeedFile(_Frozen):
    version: int
    examples: list[SeedExample]


class VerifiedExample(_Frozen):
    """One enabled verified example as the agent sees it."""

    id: uuid.UUID
    lineage_id: uuid.UUID
    version: int
    question: str
    sql: str
    description: str
    tables: list[str] = []
    metrics: list[str] = []
    allowed_roles: list[RoleName] = []
    is_active: bool = True


class VerifiedConfig(_Frozen):
    """``verified_examples`` section of config/agent.yaml."""

    enabled: bool
    max_examples: int = Field(ge=1, le=10)
    min_score: float = Field(gt=0, le=1)


VerifiedLoader = Callable[[], Awaitable[list[VerifiedExample]]]


def load_seed_file(path: Path = VERIFIED_QUERIES_FILE) -> SeedFile:
    return load_yaml_model(path, SeedFile)


def lineage_for(key: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, key)


def keywords(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1}


def similarity(question: str, example: VerifiedExample) -> float:
    """Cosine similarity of the keyword sets of the question and the example's question."""
    q = keywords(question)
    e = keywords(example.question)
    if not q or not e:
        return 0.0
    return len(q & e) / math.sqrt(len(q) * len(e))


def find_verified_examples(
    question: str,
    role: RoleName,
    examples: list[VerifiedExample],
    layer: SemanticLayer,
    config: VerifiedConfig,
    policy: SqlPolicy | None = None,
) -> list[VerifiedExample]:
    """The most similar enabled examples this role may use, best first.

    An example is offered only if it is enabled, lists the role, and its SQL passes the
    validator for this role against the current semantic layer (so a narrowed role or a
    removed column also removes the example)."""
    if not config.enabled:
        return []
    scored = sorted(
        (
            (similarity(question, ex), ex)
            for ex in examples
            if ex.is_active and role in ex.allowed_roles
        ),
        key=lambda pair: (-pair[0], pair[1].question),
    )
    chosen: list[VerifiedExample] = []
    for score, example in scored:
        if score < config.min_score or len(chosen) >= config.max_examples:
            break
        if validate(example.sql, role, layer, policy).allowed:
            chosen.append(example)
    return chosen


def examples_text(examples: list[VerifiedExample]) -> str:
    """Few-shot block for the SQL generation prompt."""
    if not examples:
        return "none"
    blocks = []
    for n, ex in enumerate(examples, start=1):
        blocks.append(
            f"Example {n}. Question: {ex.question}\n"
            f"What it does: {ex.description}\n"
            f"SQL:\n{ex.sql.strip()}"
        )
    return "\n\n".join(blocks)


# --- storage -----------------------------------------------------------------------------

_SELECT = (
    "SELECT id, lineage_id, version, question_text, sql_text, description, tables_used, "
    "metrics_used, allowed_roles, is_active FROM app.verified_queries"
)


def _row(row: Sequence[Any]) -> VerifiedExample:
    roles = [RoleName(r) for r in (row[8] or []) if r in {m.value for m in RoleName}]
    return VerifiedExample(
        id=row[0],
        lineage_id=row[1],
        version=row[2],
        question=row[3],
        sql=row[4],
        description=row[5],
        tables=list(row[6] or []),
        metrics=list(row[7] or []),
        allowed_roles=roles,
        is_active=bool(row[9]),
    )


def load_active_examples(conn: psycopg.Connection) -> list[VerifiedExample]:
    """All enabled examples (one active version per lineage)."""
    rows = conn.execute(f"{_SELECT} WHERE is_active ORDER BY question_text").fetchall()
    return [_row(r) for r in rows]


def database_verified_loader(conninfo: str) -> VerifiedLoader:
    """Read the enabled examples for every question, so changes apply at once."""

    pool = lookup_pool(conninfo)

    def load() -> list[VerifiedExample]:
        with pool.connection() as conn:
            return load_active_examples(conn)

    async def load_async() -> list[VerifiedExample]:
        return await asyncio.to_thread(load)

    return load_async


def sync_seed_examples(
    conn: psycopg.Connection, seed: SeedFile, layer: SemanticLayer, policy: SqlPolicy | None = None
) -> int:
    """Insert version 1 of each seeded example whose lineage does not exist yet.

    Lineages that already exist are left alone, so admin corrections and disabled
    examples survive a re-seed. Every example must pass the validator for its roles."""
    inserted = 0
    for ex in seed.examples:
        tables: set[str] = set()
        for role in ex.allowed_roles:
            result = validate(ex.sql, role, layer, policy)
            if not result.allowed:
                raise ValueError(
                    f"verified example {ex.key} is not valid for {role.value}: "
                    f"{result.reason_code} {result.detail}"
                )
            tables.update(result.tables)
        lineage = lineage_for(ex.key)
        exists = conn.execute(
            "SELECT 1 FROM app.verified_queries WHERE lineage_id = %s", (lineage,)
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO app.verified_queries (lineage_id, version, question_text, sql_text, "
            "description, tables_used, metrics_used, allowed_roles, is_active, verified_at) "
            "VALUES (%s, 1, %s, %s, %s, %s, %s, %s, true, now())",
            (lineage, ex.question, ex.sql.strip(), ex.description, sorted(tables),
             list(ex.metrics), [r.value for r in ex.allowed_roles]),
        )  # fmt: skip
        inserted += 1
    return inserted
