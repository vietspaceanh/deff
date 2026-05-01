from __future__ import annotations

from .base import TABLE_DEFS, TableSpec, extract_table_names
from .context import build_context
from .runner import Runner
from .render import generate_mermaid_code, result_to_html, N_ROWS


class Table:
    def __init__(self, spec: TableSpec, result=None):
        self.spec = spec
        self.result = result

    @property
    def sql(self) -> str:
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
        self.execute()
        return self.result.df()

    def refresh(self):
        self.result = None

    def fetchall(self):
        self.execute()
        return self.result.fetchall()

    def fetchmany(self, n):
        self.execute()
        return self.result.fetchmany(n)

    def fetchone(self):
        self.execute()
        return self.result.fetchone()

    def _repr_html_(self) -> str | None:
        try:
            self.execute()
            cols = self.result.columns
            types = [str(t).upper().split("(")[0] for t in self.result.types]
            rows = list(self.result.fetchmany(N_ROWS + 1))
            truncated = len(rows) == (N_ROWS + 1)
            if truncated:
                rows = rows[:N_ROWS]
            return result_to_html(cols, types, rows, truncated)
        except Exception:
            return None

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        self.execute()
        args_str = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"Table({self.func_name}({args_str}))"

    def __getattr__(self, name):
        if self.result is not None:
            return getattr(self.result, name)
        raise AttributeError(
            f"'{type(self).__name__}' has no attribute '{name}'. "
            f"Execute the table first (e.g. via sql()) to access result attributes."
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

    def execute(self, config: dict | None = None, backend: str = "duckdb"):
        if self.result is not None:
            return self.result
        self.result = Runner(build_context(self.spec, config), backend).run(self.name)
        return self.result


def sql(query, backend: str = "duckdb"):
    if isinstance(query, Table):
        query.execute()
        return query

    resolved: list[TableSpec] = []
    refs = extract_table_names(query)
    anonym_name = "current_table"

    for ref in refs:
        entry = TABLE_DEFS.get(ref)
        if entry is None:
            continue
        if isinstance(entry, TableSpec):
            ctx = build_context(entry)
            if ctx.nodes:
                Runner(ctx, backend).run(entry.name)
            resolved.append(entry)
        else:
            table = entry()
            resolved.append(table.spec)
            ctx = build_context(table.spec)
            if ctx.nodes:
                Runner(ctx, backend).run(table.name)

    runner = Runner(backend=backend)
    result = runner.execute(query)
    spec = TableSpec(
        sql=query, func_name=anonym_name, args={}, name=anonym_name,
        deps=resolved,
    )
    return Table(spec, result=result)
