from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp as sqlglot_exp

REGISTRY: dict = {}
SESSION: dict = {"last_args": {}}


@dataclass
class TableSpec:
    sql: str
    func_name: str
    args: dict
    deps: list[TableSpec] = field(default_factory=list)
    ctes: list[TableSpec] = field(default_factory=list)
    name: str = ""
    is_cte: bool = False


@dataclass
class TableNode:
    spec: TableSpec
    deps: list[str] = field(default_factory=list)
    ctes: list[TableNode] = field(default_factory=list)


def clean_sql(sql: str) -> str:
    lines = sql.strip().split("\n")
    if lines and lines[0].strip().startswith("--sql"):
        lines = lines[1:]
    result = textwrap.dedent("\n".join(lines)).strip()
    if result.endswith(";"):
        result = result[:-1].strip()
    return result


def extract_table_names(sql: str) -> set[str]:
    try:
        parsed = sqlglot.parse_one(sql, dialect="duckdb")
        tables = {t.name for t in parsed.find_all(sqlglot_exp.Table)}
        ctes = {cte.alias for cte in parsed.find_all(sqlglot_exp.CTE)}
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


def flatten_ctes(ctes: list[TableNode]) -> list[TableNode]:
    seen: set[str] = set()
    result: list[TableNode] = []
    for cte in ctes:
        for child in flatten_ctes(cte.ctes):
            if child.spec.name not in seen:
                seen.add(child.spec.name)
                result.append(child)
        if cte.spec.name not in seen:
            seen.add(cte.spec.name)
            result.append(cte)
    return result


def collect_cte_deps(ctes: list[TableNode]) -> set[str]:
    result: set[str] = set()
    for cte in ctes:
        result.update(cte.deps)
        result.update(collect_cte_deps(cte.ctes))
    return result