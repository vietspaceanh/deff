from __future__ import annotations

from dataclasses import replace
import sqlglot

from . import config
from .specs import TableSpec, flatten_ctes


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
        cte_names = {c.name for c in spec.ctes}
        for ref in spec.query.table_names:
            canonical_name = self._aliases.get(ref, ref)
            if canonical_name in cte_names:
                continue
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

    def _inline_sql(self, name: str) -> str:
        spec = self.nodes[name]
        sql = _inject_ctes(spec, flatten_ctes(spec.ctes), self._dialect)
        parsed = sqlglot.parse_one(sql, dialect=self._dialect)
        changed = False
        for table in list(parsed.find_all(sqlglot.exp.Table)):
            dep = table.name
            if dep == name or dep not in self.nodes:
                continue
            if dep in self._runtime.materialized or not self.nodes[dep].inline:
                continue
            dep_sql = self._inline_sql(dep)
            subquery = sqlglot.exp.Subquery(
                this=sqlglot.parse_one(dep_sql, dialect=self._dialect),
                alias=sqlglot.exp.TableAlias(this=sqlglot.exp.to_identifier(dep)),
            )
            joins = table.args.pop("joins", None) or []
            parent = table.parent
            table.replace(subquery)
            if joins:
                # Re-attach the table's joins to the nearest enclosing Select
                while parent is not None and not isinstance(parent, sqlglot.exp.Select):
                    parent = parent.parent
                if parent is not None:
                    parent.set("joins", (parent.args.get("joins") or []) + joins)
            changed = True
        return parsed.sql(dialect=self._dialect) if changed else sql

    def _make_ddl_str(self, name: str, sql: str) -> str:
        ddl = "TEMP TABLE" if self._dialect == "duckdb" else "TEMPORARY VIEW"
        return f"CREATE OR REPLACE {ddl} {name} AS (\n{sql}\n)"

    def statements(self, target: str, ignore_cached: bool = False) -> list[str]:
        order = self.topological_order(target)
        mat = self._runtime.materialized
        result = []

        for n in order:
            if n != target and self.nodes[n].inline:
                continue
            if ignore_cached and n in mat:
                continue
            if ignore_cached and n != target:
                mat.add(n)
            result.append(self._make_ddl_str(n, self._inline_sql(n)))

        return result

    def sql(self, target: str) -> str:
        return ";".join(self.statements(target)) + ";"


class Runtime:
    def __init__(self):
        self.tables: dict = {}
        self.swaps: dict = {}
        self.materialized: set[str] = set()
        self._graph_cache: dict[int, Graph] = {}

    def register(self, name, entry):
        self.tables[name] = entry
        self.materialized.discard(name)

    def _clear_caches(self):
        for entry in self.tables.values():
            cached = getattr(entry, '_cached_table', None)
            if cached is not None:
                cached.result = None

    def clear(self):
        self._graph_cache.clear()
        self.swaps.clear()
        self.materialized.clear()
        self._clear_caches()

    def resolve(self, name):
        return self.swaps.get(name) or self.tables.get(name)

    def graph(self, spec: TableSpec) -> Graph:
        key = id(spec)
        if key in self._graph_cache:
            return self._graph_cache[key]
        g = Graph(self, spec)
        self._graph_cache[key] = g
        return g

    def statements(self, spec: TableSpec) -> list[str]:
        return self.graph(spec).statements(spec.name)

    def get_full_sql(self, spec: TableSpec, ignore_cached: bool = False) -> str:
        return ";\n\n".join(self.graph(spec).statements(spec.name, ignore_cached=ignore_cached)) + ";"

    def swap(self, mapping):
        from .table import Table

        self._graph_cache.clear()
        self.swaps.clear()
        self.materialized.clear()
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
        
    def __repr__(self):
        tree = _table_tree(self.tables)
        swaps = f"  swaps: {len(self.swaps)} entries" if self.swaps else "  swaps: ()"
        return f"Runtime(\n  tables:\n{tree}\n{swaps}\n)"


runtime = Runtime()


# ─────────────────────────────────── Utils ────────────────────────────────── #

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


def _table_tree(tables: dict) -> str:

    def _static_edges(tfs: dict) -> dict[str, set[str]]:
        short_to_qnames: dict[str, list[str]] = {}
        for q in tfs:
            short_to_qnames.setdefault(q.split("__", 1)[-1], []).append(q)
        return {
            q: {o for name in tf.func.__code__.co_names
                if name in short_to_qnames
                for o in short_to_qnames[name] if o != q}
            for q, tf in tfs.items()
        }

    def add(q, p, last, first):
        e = tfs[q]
        s = " ✗" if e._error else (" ⚡ requires arguments" if e.args is None else " ✓")
        lines.append(f"{p}{'└── ' if last else '├── '}{q}{s}")
        if not first:
            return
        expanded.add(q)
        deps = sorted(edges.get(q, ()))
        for i, d in enumerate(deps):
            add(d, p + ("    " if last else "│   "), i == len(deps) - 1, d not in expanded)

    tfs = {n: e for n, e in tables.items() if hasattr(e, '_global_deps')}
    if not tfs:
        return "  (no tables registered)"

    edges = _static_edges(tfs)
    roots = sorted(set(tfs) - {d for deps in edges.values() for d in deps}) or sorted(tfs)
    expanded: set[str] = set()
    lines: list[str] = []

    for i, r in enumerate(roots):
        add(r, "  ", i == len(roots) - 1, True)
    for n in sorted(tfs):
        if n not in expanded:
            add(n, "  ", True, True)
    return "\n".join(lines)