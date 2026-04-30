from __future__ import annotations

from .base import REGISTRY, SESSION, TableSpec, extract_table_names, collect_cte_deps


class Context:
    def __init__(self):
        self.nodes: dict[str, TableSpec] = {}
        self._resolving: set[str] = set()

    def _process_table(self, table_spec: TableSpec, config: dict | None = None, register: bool = False):
        for dep in table_spec.deps:
            self._process_table(dep, config, register=True)

        if table_spec.name in self._resolving:
            return
        if register and table_spec.name in self.nodes:
            return
        if register:
            self._resolving.add(table_spec.name)

        referenced = extract_table_names(table_spec.sql)
        for ref in referenced:
            if ref not in self.nodes and ref not in self._resolving:
                self.resolve_name_dep(ref, config)
            if ref in self.nodes and ref != table_spec.name and ref != table_spec.func_name:
                dep_spec = self.nodes[ref]
                if dep_spec not in table_spec.deps:
                    table_spec.deps.append(dep_spec)

        for c in table_spec.ctes:
            self._process_table(c, config, register=False)

        if register:
            for dep_name in collect_cte_deps(table_spec.ctes):
                if dep_name in self.nodes and dep_name != table_spec.name:
                    dep_spec = self.nodes[dep_name]
                    if dep_spec not in table_spec.deps:
                        table_spec.deps.append(dep_spec)
            self._resolving.discard(table_spec.name)
            self.nodes[table_spec.name] = table_spec
            if table_spec.func_name != table_spec.name and table_spec.func_name not in self.nodes:
                self.nodes[table_spec.func_name] = table_spec

    def resolve_name_dep(self, name: str, config: dict | None = None):
        if name in self.nodes or name in self._resolving:
            return
        func = REGISTRY.get(name)
        if func is None:
            return

        kwargs = None
        if config and name in config:
            kwargs = config[name]
        elif name in SESSION.get("last_args", {}):
            kwargs = SESSION["last_args"][name]
        if kwargs is None:
            kwargs = func.get_default_kwargs()
            if kwargs is None:
                return

        table = func(**kwargs)
        resolved = TableSpec(
            sql=table.sql, func_name=name, args=kwargs, name=name,
            deps=list(table.deps), ctes=list(table.ctes),
        )
        self._process_table(resolved, config, register=True)
        if resolved.name != name and name not in self.nodes:
            self.nodes[name] = self.nodes[resolved.name]

    def topological_order(self, target: str) -> list[str]:
        visited: set[str] = set()
        visiting: set[str] = set()
        order: list[str] = []

        def visit(name):
            if name in visited:
                return
            if name in visiting:
                raise ValueError(f"Circular dependency: {name}")
            visiting.add(name)
            spec = self.nodes.get(name)
            if spec is not None:
                for dep in spec.deps:
                    visit(dep.name)
            visiting.discard(name)
            visited.add(name)
            order.append(name)

        visit(target)
        return order


def build_context(table_spec: TableSpec, config: dict | None = None) -> Context:
    ctx = Context()
    ctx._process_table(table_spec, config, register=True)
    return ctx
