from __future__ import annotations

import re
import textwrap
from dataclasses import replace

import sqlglot

from . import config
from .specs import Query, TableSpec, flatten_ctes

_MARKER = "\x00"
_TABLE_REF_RE = re.compile(_MARKER + r"(\w+)" + _MARKER)


class Graph:
    def __init__(self, runtime: Runtime, spec: TableSpec):
        self.nodes: dict[str, TableSpec] = {}
        self.edges: dict[str, set[str]] = {}
        self._runtime = runtime
        self._aliases: dict[str, str] = {}
        self._dialect = config.dialect
        self._build_graph(spec)

    def _resolve_ref(self, ref: str) -> TableSpec | None:
        entry = self._runtime.resolve(ref)
        if entry is None:
            return
        if isinstance(entry, TableSpec):
            return entry
        if entry.args is None:
            return
        return entry(**entry.args).spec

    def _build_graph(self, spec: TableSpec) -> None:
        if spec.name in self.nodes:
            if not spec.is_cte:
                return
        else:
            self.nodes[spec.name] = spec
            if spec.func_name != spec.name:
                self._aliases[spec.func_name] = spec.name
        self._process_references(spec)
        self._process_ctes(spec)

    def _process_references(self, spec: TableSpec) -> None:
        for ref in spec.query.table_names:
            canonical_name = self._aliases.get(ref, ref)
            if canonical_name not in self.nodes:
                resolved = self._resolve_ref(ref)
                if resolved is not None:
                    self._build_graph(resolved)
            if canonical_name in self.nodes and canonical_name != spec.name:
                self.edges.setdefault(spec.name, set()).add(canonical_name)

    def _process_ctes(self, spec: TableSpec) -> None:
        cte_names = {c.name for c in spec.ctes}
        for c in reversed(spec.ctes):
            self._build_graph(c)
            for dep in self.edges.get(c.name, set()):
                if dep not in cte_names:
                    self.edges.setdefault(spec.name, set()).add(dep)

    def topological_order(self, target: str) -> list[str]:
        order, visiting = [], set()
        target = self._aliases.get(target, target)

        def visit(name):
            if name in order:
                return
            if name in visiting:
                raise ValueError(f"Circular dependency: {name}")
            visiting.add(name)
            for dep in self.edges.get(name, set()):
                visit(dep)
            visiting.discard(name)
            order.append(name)

        visit(target)
        return order

    def statements(self, target: str) -> list[str]:
        ddl = "TEMP TABLE" if self._dialect == "duckdb" else "TEMPORARY VIEW"
        return [f"CREATE OR REPLACE {ddl} {n} AS ({_inject_ctes(self.nodes[n], flatten_ctes(self.nodes[n].ctes), self._dialect)})" for n in self.topological_order(target)]

    def sql(self, target: str) -> str:
        return ";\n\n".join(self.statements(target)) + ";"


def _inject_ctes(spec: TableSpec, ctes: list[TableSpec], dialect: str) -> str:
    if not ctes:
        return spec.sql
    parsed = spec.parsed.copy()
    new_ctes = _build_cte_exprs(ctes)
    existing_with = parsed.args.get("with_")
    if existing_with:
        existing_with.set("expressions", new_ctes + list(existing_with.expressions))
    else:
        parsed.set("with_", sqlglot.exp.With(expressions=new_ctes))
    return parsed.sql(dialect=dialect)


def _build_cte_exprs(ctes: list[TableSpec]) -> list:
    exprs = []
    for cte in ctes:
        cte_query = cte.parsed.copy()
        exprs.append(
            sqlglot.exp.CTE(
                this=cte_query,
                alias=sqlglot.exp.TableAlias(
                    this=sqlglot.exp.to_identifier(cte.name),
                ),
            )
        )
    return exprs


def _clean_sql(sql: str) -> str:
    """Normalize SQL: strip --sql header, dedent, remove trailing semicolon."""
    lines = sql.strip().split("\n")
    if lines and lines[0].strip().startswith("--sql"):
        lines = lines[1:]
    result = textwrap.dedent("\n".join(lines)).strip()
    if result.endswith(";"):
        result = result[:-1].strip()
    return result


class Runtime:
    def __init__(self):
        self.tables: dict = {}
        self.swaps: dict = {}
        self._graph_cache: dict[int, Graph] = {}

    def register(self, name, entry):
        self.tables[name] = entry

    def _clear_caches(self):
        for entry in self.tables.values():
            cached = getattr(entry, '_cached_table', None)
            if cached is not None:
                cached.result = None

    def clear(self):
        self._graph_cache.clear()
        self.swaps.clear()
        self._clear_caches()

    def resolve(self, name):
        return self.swaps.get(name) or self.tables.get(name)

    def validate_sql(self, sql: str) -> Query:
        """Check for bare registered table names, strip markers, normalize.

        Identifies table references by parsing with sqlglot and checking
        FROM/JOIN Table nodes and column qualifiers (e.g. transactions.*).
        This avoids false positives from string literals or aliases.

        Returns a ``Query`` with the cleaned SQL and optional lazy-parsed AST.
        """
        cleaned = _TABLE_REF_RE.sub("__TBL_SAFE__", sql)
        try:
            parsed = sqlglot.parse_one(cleaned, dialect=config.dialect)
            for identifier in parsed.find_all(sqlglot.exp.Identifier):
                parent_name = type(identifier.parent).__name__
                arg_key = identifier.arg_key
                # Table in FROM/JOIN, or table qualifier in col ref like transactions.col / transactions.*
                if (parent_name == "Table" and arg_key == "this") or (
                    parent_name == "Column" and arg_key == "table"
                ):
                    if identifier.name in self.tables:
                        raise ValueError(
                            f"Table '{identifier.name}' is a registered table but was referenced as a raw string. "
                            f"Use f'...{{{identifier.name}}}...' to reference it by variable."
                        )
        except sqlglot.errors.ParseError:
            pass
        return Query(sql=_clean_sql(_TABLE_REF_RE.sub(r"\1", sql)))

    def graph(self, spec: TableSpec) -> Graph:
        key = id(spec)
        if key in self._graph_cache:
            return self._graph_cache[key]
        g = Graph(self, spec)
        self._graph_cache[key] = g
        return g

    def statements(self, spec: TableSpec) -> list[str]:
        return self.graph(spec).statements(spec.name)

    def full_sql(self, spec: TableSpec) -> str:
        return ";\n\n".join(self.statements(spec)) + ";"

    def swap(self, mapping):
        from .table import Table

        self._graph_cache.clear()
        self.swaps.clear()
        for target, replacement in mapping.items():
            name = target.name if hasattr(target, 'name') else str(target)
            if isinstance(replacement, Table):
                spec = replacement.spec
            elif isinstance(replacement, TableSpec):
                spec = replacement
            else:
                spec = replacement().spec
            self.swaps[name] = replace(spec, name=name, deps=list(spec.deps))
        self._clear_caches()


def mark_ref(name: str) -> str:
    """Wrap a table name so validate_sql can recognize it as a variable ref."""
    return f"{_MARKER}{name}{_MARKER}"


runtime = Runtime()