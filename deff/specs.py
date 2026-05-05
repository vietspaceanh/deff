from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot

from . import config


@dataclass
class TableSpec:
    query: Query
    func_name: str | None
    name: str | None
    args: dict = field(default_factory=dict)
    deps: list[TableSpec] = field(default_factory=list)
    ctes: list[TableSpec] = field(default_factory=list)
    is_cte: bool = False
    is_adhoc: bool = False

    @property
    def sql(self) -> str:
        return self.query.sql

    @property
    def parsed(self):
        return self.query.parsed


class Query:
    def __init__(self, sql: str):
        self.sql = sql
        self.parsed = sqlglot.parse_one(self.sql, dialect=config.dialect)

    @property
    def table_references(self) -> set[str]:
        """All table-like identifiers: FROM/JOIN table names and column qualifiers."""
        refs: set[str] = set()
        for identifier in self.parsed.find_all(sqlglot.exp.Identifier):
            parent_name = type(identifier.parent).__name__
            arg_key = identifier.arg_key
            if (parent_name == "Table" and arg_key == "this") or (
                parent_name == "Column" and arg_key == "table"
            ):
                refs.add(identifier.name)
        return refs

    @property
    def table_names(self) -> set[str]:
        """FROM/JOIN table names minus CTEs (for dependency resolution)."""
        tables = {t.name for t in self.parsed.find_all(sqlglot.exp.Table)}
        ctes = {cte.alias for cte in self.parsed.find_all(sqlglot.exp.CTE)}
        return tables - ctes


def sanitize_alias(func_name: str, args: dict) -> str:
    if not args:
        return func_name
    parts = [v.name if hasattr(v, "name") else str(v) for v in args.values()]
    raw = "_".join(parts)
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", raw)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return f"{func_name}__{sanitized}"


def flatten_ctes(ctes: list[TableSpec]) -> list[TableSpec]:
    seen: set[str] = set()
    result: list[TableSpec] = []
    for cte in ctes:
        for child in flatten_ctes(cte.ctes):
            if child.name not in seen:
                seen.add(child.name)
                result.append(child)
        if cte.name not in seen:
            seen.add(cte.name)
            result.append(cte)
    return result
