from __future__ import annotations

import sqlglot
from sqlglot import exp as sqlglot_exp

from .base import Result
from .. import config as global_config
from ..specs import TableSpec, flatten_ctes
from ..context import Context


class Runner:
    def __init__(self, ctx: Context | None = None, dialect: str | None = None):
        self.ctx = ctx
        self.dialect = dialect if dialect is not None else global_config.dialect

    def get(self, target: str) -> Result:
        for stmt in self.build_statements(target):
            self.sql(stmt)
        if self.dialect == "duckdb":
            return self.sql(f"TABLE {target}")
        return self.sql(f"SELECT * FROM {target}")

    def build_statements(self, target: str) -> list[str]:
        order = self.ctx.topological_order(target)
        statements = []
        ddl = "TEMP TABLE" if self.dialect == "duckdb" else "TEMPORARY VIEW"
        for name in order:
            spec = self.ctx.nodes[name]
            ctes = flatten_ctes(spec.ctes)
            sql = self._inject_ctes(spec, ctes)
            statements.append(f"CREATE OR REPLACE {ddl} {name} AS ({sql})")
        return statements

    def sql(self, query: str) -> Result:
        if self.dialect == "duckdb":
            import duckdb
            from .duckdb import DuckDBResult
            return DuckDBResult(duckdb.sql(query))
        if self.dialect == "spark":
            from pyspark.sql import SparkSession
            from .spark import SparkResult
            spark = SparkSession.builder.getOrCreate()
            return SparkResult(spark.sql(query))
        raise ValueError(f"Unsupported backend: {self.dialect}")

    def _sqlglot_dialect(self) -> str:
        return {"duckdb": "duckdb", "spark": "spark"}.get(self.dialect, "duckdb")

    def _inject_ctes(self, spec: TableSpec, ctes: list[TableSpec]) -> str:
        if not ctes:
            return spec.sql
        dialect = self._sqlglot_dialect()
        parsed = spec.parsed.copy()
        new_ctes = self._build_cte_exprs(ctes)
        existing_with = parsed.args.get("with_")
        if existing_with:
            existing_with.set("expressions", new_ctes + list(existing_with.expressions))
        else:
            parsed.set("with_", sqlglot_exp.With(expressions=new_ctes))
        return parsed.sql(dialect=dialect)

    def _build_cte_exprs(self, ctes: list[TableSpec]) -> list:
        dialect = self._sqlglot_dialect()
        exprs = []
        for cte in ctes:
            cte_query = cte.parsed.copy()
            exprs.append(
                sqlglot_exp.CTE(
                    this=cte_query,
                    alias=sqlglot_exp.TableAlias(
                        this=sqlglot_exp.to_identifier(cte.name),
                    ),
                )
            )
        return exprs
