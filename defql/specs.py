from __future__ import annotations

import re
import textwrap
from typing import Any

import sqlglot
from dataclasses import dataclass, field

from . import config

TABLE_DEFS: dict = {}


@dataclass
class TableSpec:
    sql: str
    func_name: str
    name: str
    args: dict = field(default_factory=dict)
    deps: list[TableSpec] = field(default_factory=list)
    ctes: list[TableSpec] = field(default_factory=list)
    is_cte: bool = False
    _parsed: Any = field(init=False, repr=False, default=None)

    @property
    def parsed(self) -> sqlglot.exp.Expression:
        if self._parsed is None:
            self._parsed = sqlglot.parse_one(self.sql, dialect=config.dialect)
        return self._parsed


def clean_sql(sql: str) -> str:
    lines = sql.strip().split("\n")
    if lines and lines[0].strip().startswith("--sql"):
        lines = lines[1:]
    result = textwrap.dedent("\n".join(lines)).strip()
    if result.endswith(";"):
        result = result[:-1].strip()
    return result


def extract_table_names(sql: str | sqlglot.exp.Expression) -> set[str]:
    try:
        if isinstance(sql, sqlglot.exp.Expression):
            parsed = sql
        else:
            parsed = sqlglot.parse_one(sql, dialect=config.dialect)
        tables = {t.name for t in parsed.find_all(sqlglot.exp.Table)}
        ctes = {cte.alias for cte in parsed.find_all(sqlglot.exp.CTE)}
        return tables - ctes
    except sqlglot.errors.ParseError:
        return set()


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


def collect_cte_deps(ctes: list[TableSpec]) -> set[str]:
    result: set[str] = set()
    for cte in ctes:
        result.update(d.name for d in cte.deps)
        result.update(collect_cte_deps(cte.ctes))
    return result
