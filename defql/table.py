from __future__ import annotations

import inspect

from .base import TableSpec, clean_sql, extract_table_names, sanitize_alias
from .context import Context, build_context
from .runner import Runner
from .render import generate_mermaid_code


class Table:
    def __init__(
        self,
        sql: str,
        func_name: str,
        args: dict,
        deps: list[TableSpec] | None = None,
        ctes: list[TableSpec] | None = None,
        is_cte: bool = False,
        result=None,
    ):
        name = sanitize_alias(func_name, args)
        self.spec = TableSpec(
            sql=clean_sql(sql), func_name=func_name, args=args,
            deps=deps or [], ctes=ctes or [],
            name=name, is_cte=is_cte,
        )
        self.result = result
        self._cached_rows = None
        self._cached_cols = None
        self._cached_types = None
        self._fully_cached = False

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
        ctx = build_context(self.spec)
        return ";\n\n".join(Runner().build_statements(ctx, self.name)) + ";"

    @property
    def graph(self):
        print(generate_mermaid_code(self.spec))

    @property
    def df(self):
        _execute_table(self)
        return self.result.df()

    def fetchall(self):
        _execute_table(self)
        if self._fully_cached:
            return list(self._cached_rows)
        return self.result.fetchall()

    def fetchmany(self, n):
        _execute_table(self)
        if self._fully_cached:
            return list(self._cached_rows[:n])
        return self.result.fetchmany(n)

    def fetchone(self):
        _execute_table(self)
        if self._fully_cached:
            return self._cached_rows[0] if self._cached_rows else None
        return self.result.fetchone()

    def _repr_html_(self) -> str | None:
        try:
            _execute_table(self)
            from .render import N_ROWS, result_to_html
            cols = self.result.columns
            types = [str(t).upper().split("(")[0] for t in self.result.types]
            rows = list(self.result.fetchmany(N_ROWS + 1))
            truncated = len(rows) == (N_ROWS + 1)
            if truncated:
                rows = rows[:N_ROWS]
            self._cached_cols = cols
            self._cached_types = types
            self._cached_rows = rows
            self._fully_cached = True
            return result_to_html(cols, types, rows, truncated)
        except Exception:
            return None

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
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


def sql(query, *args, **kwargs):
    import duckdb

    if isinstance(query, Table):
        _execute_table(query)
        return query

    backend = kwargs.pop("backend", "duckdb")
    resolved: list[Table] = []
    refs = extract_table_names(query)
    anonym_name = "current_table"

    for ref in refs:
        ctx = Context()
        ctx.resolve_name_dep(ref, None)
        if ctx.nodes:
            Runner(backend=backend).run(ctx, ref)

    frame = inspect.currentframe().f_back
    for name, val in {**frame.f_globals, **frame.f_locals}.items():
        if isinstance(val, Table) and val.func_name != anonym_name:
            if val.name in refs or val.func_name in refs:
                resolved.append(val)
                _execute_table(val)
                if name != val.name:
                    duckdb.sql(f'CREATE OR REPLACE TEMP VIEW "{name}" AS TABLE "{val.name}"')

    if backend == "duckdb":
        duckdb_result = duckdb.sql(query, *args, **kwargs)
        return Table(
            sql=query, func_name=anonym_name, args={},
            deps=[r.spec for r in resolved],
            result=duckdb_result,
        )
    raise ValueError(f"Unsupported backend: {backend}")


def _execute_table(table: Table, config: dict | None = None, backend: str = "duckdb"):
    if table.result is not None:
        return table.result
    table.result = Runner(backend=backend).run(
        build_context(table.spec, config), table.name
    )
    return table.result
