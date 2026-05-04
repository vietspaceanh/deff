from __future__ import annotations

from . import config
from .runtime import runtime
from .specs import TableSpec, extract_table_names
from .runner import Runner
from .render import generate_mermaid_code, result_to_html

TMP_TABLE_NAME = 'current_table'


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
        return runtime.full_sql(self.spec)

    @property
    def graph(self):
        print(generate_mermaid_code(self.spec))

    @property
    def df(self):
        return self.get().df()

    @property
    def columns(self):
        return self.get().columns
    
    @property
    def schema(self):
        return self.sql(f"DESCRIBE {self.name}")

    @property
    def stats(self):
        return self.sql(f"SUMMARIZE {self.name}")

    def refresh(self):
        self.result = None

    def get(self):
        if self.result is not None:
            return self.result
        runner = Runner()
        runner.sql(runtime.full_sql(self.spec))
        self.result = runner.sql(f"TABLE {self.name}")
        return self.result

    def sql(self, query: str):
        self.get()
        result = Runner().sql(query)
        return Table(
            TableSpec(
                sql=query,
                func_name=TMP_TABLE_NAME,
                name=TMP_TABLE_NAME,
                deps=list(self.spec.deps),
                is_adhoc=True,
            ),
            result=result,
        )

    def __or__(self, query: str):
        source = f"({self.raw_sql})" if self.spec.is_adhoc else self.name
        completed_query = f"FROM {source} {query}"
        return self.sql(completed_query)
    
    def __getitem__(self, cols: str):
        """Quickly get columns (as an expression)."""
        return self.__or__(f"SELECT {cols}")

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
        self.get()
        cols = self.result.columns
        types = self.result.types
        rows = list(self.result.fetchmany(config.rows + 1))
        truncated = len(rows) == (config.rows + 1)
        if truncated:
            rows = rows[:config.rows]
        return result_to_html(cols, types, rows, truncated)

    def __str__(self) -> str:
        if self.spec.is_adhoc:
            return f"({self.raw_sql})"
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


def sql(query, name=TMP_TABLE_NAME):
    if isinstance(query, Table):
        query.get()
        return query

    resolved: list[TableSpec] = []
    refs = extract_table_names(query)
    runner = Runner()

    all_stmts: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        entry = runtime.resolve(ref)
        if entry is None:
            continue
        if isinstance(entry, TableSpec):
            spec = entry
            resolved.append(spec)
            for stmt in runtime.statements(spec):
                if stmt not in seen:
                    seen.add(stmt)
                    all_stmts.append(stmt)
        else:
            table = entry()
            table.get()
            resolved.append(table.spec)

    if all_stmts:
        runner.sql(";\n\n".join(all_stmts) + ";")

    result = runner.sql(query)
    is_adhoc = (name == TMP_TABLE_NAME)
    spec = TableSpec(
        sql=query, func_name=name, args={}, name=name,
        deps=resolved,
        is_adhoc=is_adhoc,
    )
    if not is_adhoc:
        runtime.register(name, spec)
    return Table(spec, result=result)
