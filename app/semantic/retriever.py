"""Keyword and synonym retrieval over the semantic layer, filtered by role.

Approach (docs/decisions-log.md, Step 7): the question is normalised into word tokens
(lower case, simple singular form). Every table, column, metric name and business
synonym is a phrase; a phrase matches when its tokens appear in order in the question.
Matched tables, the tables of matched columns and metrics, and the tables on the
shortest join path between them form the context. Everything the role may not use is
removed before anything is returned.
"""

import re
from collections import deque

from pydantic import BaseModel, ConfigDict

from app.core.enums import RoleName
from app.semantic.models import JoinDef, SemanticLayer


class RetrievedColumn(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    examples: list[str]


class RetrievedTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    columns: list[RetrievedColumn]


class RetrievedMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    definition: str
    tables: list[str]
    join: str | None


class RetrievedContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    semantic_version: int
    tables: list[RetrievedTable]
    joins: list[JoinDef]
    metrics: list[RetrievedMetric]
    matched_terms: list[str]

    @property
    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]

    @property
    def metric_names(self) -> list[str]:
        return [m.name for m in self.metrics]


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [_singular(w) for w in re.findall(r"[a-z0-9]+", text.lower())]


def _contains(tokens: list[str], phrase: list[str]) -> bool:
    n = len(phrase)
    return n > 0 and any(tokens[i : i + n] == phrase for i in range(len(tokens) - n + 1))


def _terms(layer: SemanticLayer) -> list[tuple[str, str]]:
    """(phrase, target) pairs; targets use the synonym format kind:name."""
    terms: list[tuple[str, str]] = []
    for t_name, table in layer.tables.items():
        terms.append((t_name.replace("_", " "), f"table:{t_name}"))
        for c_name in table.columns:
            terms.append((c_name.replace("_", " "), f"column:{t_name}.{c_name}"))
    for m_name, metric in layer.metrics.items():
        terms.append((m_name.replace("_", " "), f"metric:{m_name}"))
        terms.extend((syn, f"metric:{m_name}") for syn in metric.synonyms)
    terms.extend(layer.synonyms.items())
    return terms


def _join_path(start: str, goal: str, joins: list[JoinDef], allowed: set[str]) -> list[str]:
    graph: dict[str, set[str]] = {}
    for j in joins:
        if j.left in allowed and j.right in allowed:
            graph.setdefault(j.left, set()).add(j.right)
            graph.setdefault(j.right, set()).add(j.left)
    queue: deque[list[str]] = deque([[start]])
    seen = {start}
    while queue:
        path = queue.popleft()
        if path[-1] == goal:
            return path
        for nxt in sorted(graph.get(path[-1], set()) - seen):
            seen.add(nxt)
            queue.append([*path, nxt])
    return []


def retrieve(question: str, role: RoleName, layer: SemanticLayer) -> RetrievedContext:
    """Return the tables, columns, joins and metrics relevant to ``question`` for ``role``."""
    tokens = tokenize(question)
    allowed_tables = {n for n, t in layer.tables.items() if role in t.allowed_roles}
    allowed_metrics = {
        n
        for n, m in layer.metrics.items()
        if role in m.allowed_roles and set(m.table_names) <= allowed_tables
    }

    matched_terms: list[str] = []
    tables: set[str] = set()
    metrics: set[str] = set()
    for phrase, target in _terms(layer):
        if not _contains(tokens, tokenize(phrase)):
            continue
        kind, _, name = target.partition(":")
        if kind == "table" and name in allowed_tables:
            tables.add(name)
        elif kind == "column":
            t_name, _, c_name = name.partition(".")
            column = layer.tables[t_name].columns[c_name]
            if t_name in allowed_tables and role in column.allowed_roles:
                tables.add(t_name)
        elif kind == "metric" and name in allowed_metrics:
            metrics.add(name)
            tables.update(layer.metrics[name].table_names)
        else:
            continue
        matched_terms.append(phrase)

    # Add tables on the shortest join path between the matched ones.
    ordered = sorted(tables)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            tables.update(_join_path(a, b, layer.joins, allowed_tables))

    return RetrievedContext(
        semantic_version=layer.version,
        tables=[
            RetrievedTable(
                name=t_name,
                description=layer.tables[t_name].description,
                columns=[
                    RetrievedColumn(name=c_name, description=c.description, examples=c.examples)
                    for c_name, c in layer.tables[t_name].columns.items()
                    if role in c.allowed_roles
                ],
            )
            for t_name in sorted(tables)
        ],
        joins=[j for j in layer.joins if j.left in tables and j.right in tables],
        metrics=[
            RetrievedMetric(
                name=m_name,
                description=layer.metrics[m_name].description,
                definition=layer.metrics[m_name].definition,
                tables=list(layer.metrics[m_name].tables),
                join=layer.metrics[m_name].join,
            )
            for m_name in sorted(metrics)
        ],
        matched_terms=sorted(set(matched_terms)),
    )
