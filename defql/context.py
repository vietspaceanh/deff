from __future__ import annotations

from .base import (
    REGISTRY,
    SESSION,
    TableSpec,
    TableNode,
    extract_table_names,
    collect_cte_deps,
)


class Context:
    def __init__(self):
        self.nodes: dict[str, TableNode] = {}
        self._resolving: set[str] = set()

    def add_table(self, table_spec: TableSpec, config: dict | None = None):
        self._process_table(table_spec, config, register=True)

    def _process_table(self, table_spec: TableSpec, config: dict | None = None, register: bool = False):
        for dep in table_spec.deps:
            self.add_table(dep, config)

        if table_spec.name in self._resolving:
            return None
        if register and table_spec.name in self.nodes:
            return self.nodes[table_spec.name]
        if register:
            self._resolving.add(table_spec.name)

        referenced = extract_table_names(table_spec.sql)
        for ref in referenced:
            if ref not in self.nodes and ref not in self._resolving:
                self.resolve_name_dep(ref, config)

        all_dep_names = [d.name for d in table_spec.deps]
        all_dep_names += [ref for ref in referenced if ref in self.nodes]

        cte_nodes_raw = [self._process_table(c, config, register=False) for c in table_spec.ctes]
        cte_nodes = [n for n in cte_nodes_raw if n is not None]

        node = TableNode(
            spec=table_spec,
            deps=list(set(all_dep_names) | collect_cte_deps(cte_nodes)),
            ctes=cte_nodes,
        )

        if register:
            self._resolving.discard(table_spec.name)
            self.nodes[table_spec.name] = node
            if table_spec.func_name != table_spec.name and table_spec.func_name not in self.nodes:
                self.nodes[table_spec.func_name] = node

        return node

    def build_cte_node(self, table_spec: TableSpec, config: dict | None = None) -> TableNode:
        return self._process_table(table_spec, config, register=False)

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

        self._resolving.add(name)
        table = func(**kwargs)

        for dep in table.deps:
            self.add_table(dep, config)

        referenced = extract_table_names(table.sql)
        for ref in referenced:
            self.resolve_name_dep(ref, config)

        all_dep_names = [d.name for d in table.deps]
        all_dep_names += [ref for ref in referenced if ref in self.nodes]

        cte_nodes_raw = [self.build_cte_node(c, config) for c in table.ctes]
        cte_nodes = [n for n in cte_nodes_raw if n is not None]

        self._resolving.discard(name)
        self.nodes[name] = TableNode(
            spec=TableSpec(
                sql=table.sql,
                func_name=name,
                args=kwargs,
                name=name,
            ),
            deps=list(set(all_dep_names) | collect_cte_deps(cte_nodes)),
            ctes=cte_nodes,
        )

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
            if name in self.nodes:
                for dep in self.nodes[name].deps:
                    visit(dep)
            visiting.discard(name)
            visited.add(name)
            order.append(name)

        visit(target)
        return order


def build_context(table_spec: TableSpec, config: dict | None = None) -> Context:
    ctx = Context()

    for dep in table_spec.deps:
        ctx.add_table(dep, config)

    referenced = extract_table_names(table_spec.sql)
    for ref in referenced:
        if ref != table_spec.name and ref != table_spec.func_name:
            ctx.resolve_name_dep(ref, config)

    all_dep_names = [d.name for d in table_spec.deps]
    all_dep_names += [ref for ref in referenced if ref in ctx.nodes]

    cte_nodes = [ctx.build_cte_node(c, config) for c in table_spec.ctes]

    node = TableNode(
        spec=table_spec,
        deps=list(set(all_dep_names) - {table_spec.name} | collect_cte_deps(cte_nodes)),
        ctes=cte_nodes,
    )
    ctx.nodes[table_spec.name] = node
    if table_spec.func_name != table_spec.name and table_spec.func_name not in ctx.nodes:
        ctx.nodes[table_spec.func_name] = node

    return ctx