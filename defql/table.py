from __future__ import annotations

from . import config
from .specs import TABLE_DEFS, TableSpec, extract_table_names
from .context import build_context
from .runner import Runner
from .render import generate_mermaid_code, result_to_html


class Table:
    def __init__(self, spec: TableSpec, result=None):
        self.spec = spec
        self.result = result

    @property
    def raw_sql(self) -> str:
        return self.spec.sql

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def deps(self):
        return self.spec.deps

    @property
    def ctes(self):
        return self.spec.ctes

    @property
    def func_name(self) -> str:
        return self.spec.func_name

    @property
    def args(self) -> dict:
        return self.spec.args

    @property
    def is_cte(self) -> bool:
        return self.spec.is_cte

    @property
    def full_sql(self) -> str:
        return ";\n\n".join(Runner(build_context(self.spec)).build_statements(self.name)) + ";"

    @property
    def graph(self):
        print(generate_mermaid_code(self.spec))

    @property
    def df(self):
        self.get()
        return self.result.df()

    def refresh(self):
        self.result = None

    def get(self, config: dict | None = None):
        if self.result is not None:
            return self.result
        self.result = Runner(build_context(self.spec, config)).get(self.name)
        return self.result

    def sql(self, query: str):
        self.get()
        runner = Runner()
        result = runner.sql(f"FROM {self.name} {query}")
        return Table(
            TableSpec(
                sql=f"FROM {self.name} {query}",
                func_name=self.func_name,
                name=self.name,
                deps=[self.spec],
            ),
            result=result,
        )

    def fetchall(self):
        self.get()
        return self.result.fetchall()

    def fetchmany(self, n):
        self.get()
        return self.result.fetchmany(n)

    def fetchone(self):
        self.get()
        return self.result.fetchone()

    def _repr_html_(self) -> str | None:
        try:
            self.get()
            cols = self.result.columns
            types = self.result.types
            rows = list(self.result.fetchmany(config.rows + 1))
            truncated = len(rows) == (config.rows + 1)
            if truncated:
                rows = rows[:config.rows]
            return result_to_html(cols, types, rows, truncated)
        except Exception:
            return None

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        self.get()
        args_str = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"Table({self.func_name}({args_str}))"

    def __getattr__(self, name):
        if self.result is not None:
            return getattr(self.result, name)
        raise AttributeError(
            f"'{type(self).__name__}' has no attribute '{name}'. "
            f"Run get() first to access result attributes."
        )

    def __iter__(self):
        if self.result is None:
            raise RuntimeError("Table has not been executed yet")
        return iter(self.result)

    def __len__(self):
        if self.result is None:
            raise RuntimeError("Table has not been executed yet")
        return len(self.result)

    def __bool__(self):
        return True


def sql(query, name='current_table'):
    if isinstance(query, Table):
        query.get()
        return query

    resolved: list[TableSpec] = []
    refs = extract_table_names(query)

    for ref in refs:
        entry = TABLE_DEFS.get(ref)
        if entry is None:
            continue
        if isinstance(entry, TableSpec):
            ctx = build_context(entry)
            if ctx.nodes:
                Runner(ctx).get(entry.name)
            resolved.append(entry)
        else:
            table = entry()
            resolved.append(table.spec)
            ctx = build_context(table.spec)
            if ctx.nodes:
                Runner(ctx).get(table.name)

    runner = Runner()
    result = runner.sql(query)
    spec = TableSpec(
        sql=query, func_name=name, args={}, name=name,
        deps=resolved,
    )
    if name != 'current_table':
        TABLE_DEFS[name] = spec
    return Table(spec, result=result)
