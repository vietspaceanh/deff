from __future__ import annotations

from dataclasses import replace
import sqlglot

from . import config
from .specs import TableSpec, extract_table_names, flatten_ctes


class Graph:
    def __init__(self, runtime: Runtime, spec: TableSpec):
        self._runtime = runtime
        self.nodes: dict[str, TableSpec] = {}
        self.edges: dict[str, set[str]] = {}
        self._aliases: dict[str, str] = {}
        self._dialect = config.dialect
        self._process(spec)

    def _process(self, spec: TableSpec):
        if spec.name in self.nodes:
            return
        self.nodes[spec.name] = spec
        if spec.func_name != spec.name:
            self._aliases[spec.func_name] = spec.name

        def canon(name): return self._aliases.get(name, name)

        for ref in extract_table_names(spec.parsed):
            if canon(ref) not in self.nodes:
                entry = self._runtime.resolve(ref)
                if entry is None:
                    continue
                s = entry if isinstance(entry, TableSpec) else entry(**entry.get_default_kwargs() or {}).spec
                self._process(s)
            if canon(ref) in self.nodes and canon(ref) != spec.name:
                self.edges.setdefault(spec.name, set()).add(canon(ref))

        cte_names = {c.name for c in spec.ctes}
        for c in reversed([c for c in spec.ctes if c.name not in self.nodes]):
            self._process(c)
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


runtime = Runtime()
