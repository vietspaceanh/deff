from __future__ import annotations

import re
import textwrap
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
    def __init__(self, sql: str, func_name: str | None = None):
        self.sql = self._clean_sql(sql)
        self.func_name = func_name
        
        try:
            self.parsed = sqlglot.parse_one(self.sql, dialect=config.dialect)
        except Exception as exception:
            exception.args = (format_error(exception.errors[0], self.sql, self.func_name), )
            raise

    @staticmethod
    def _clean_sql(sql: str) -> str:
        """Normalize SQL: strip '--sql' header, dedent, remove trailing semicolon."""
        lines = sql.strip().split("\n")
        if lines and lines[0].strip().startswith("--sql"):
            lines = lines[1:]
        result = textwrap.dedent("\n".join(lines)).strip()
        if result.endswith(";"):
            result = result[:-1].strip()
        return result

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


def format_error(err: dict, query: str = None, func_name: str = None) -> str:
    """Return a colorized error string with ±10 context lines."""
    RED = '\033[31m'
    BLUE = '\033[34m'
    GREY = '\033[90m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    
    lines_out = []
    lines_out.append(
        f"{RED}{err['description']} (line {err['line']}, col {err['col']}){RESET}"
        f"\nTable: {BOLD}{BLUE}{func_name}{RESET}" if func_name else ""
    )

    if not query:
        ctx = err['start_context'] + f"{RED}{BOLD}{err['highlight']}{RESET}" + err['end_context']
        lines_out.append(f"  {ctx}")
        return '\n'.join(lines_out)

    lines = query.split('\n')
    line_idx = err['line'] - 1
    start = max(0, line_idx - 10)
    end = min(len(lines), line_idx + 11)

    for i in range(start, end):
        line = lines[i]
        line_num = i + 1
        prefix = f"{line_num:4d} | "
        if line_num == err['line']:
            lines_out.append(f"{prefix}{BOLD}{line}{RESET}")
            caret = ' ' * (len(prefix) + err['col'] - 1) + '^'
            lines_out.append(f"{RED}{BOLD}{caret}{RESET}")
        elif line_num == err['line'] - 1:
            lines_out.append(f"{prefix}{BOLD}{line}{RESET}")
        else:
            lines_out.append(f"{GREY}{prefix}{RESET}{line}{RESET}")

    return '\n'.join(lines_out)