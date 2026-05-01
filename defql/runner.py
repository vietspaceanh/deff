from __future__ import annotations

import sqlglot
from sqlglot import exp as sqlglot_exp

from .base import TableSpec, flatten_ctes
from .context import Context


class Runner:
    def __init__(self, ctx: Context | None = None, backend: str = "duckdb"):
        self.ctx = ctx
        self.backend = backend

    def get(self, target: str):
        for stmt in self.build_statements(target):
            self.sql(stmt)
        return self.sql(f"TABLE {target}")

    def build_statements(self, target: str) -> list[str]:
        order = self.ctx.topological_order(target)
        statements = []
        for name in order:
            spec = self.ctx.nodes[name]
            ctes = flatten_ctes(spec.ctes)
            sql = self._inject_ctes(spec.sql, ctes)
            statements.append(f"CREATE OR REPLACE TEMP TABLE {name} AS ({sql})")
        return statements

    def sql(self, query: str):
        if self.backend == "duckdb":
            import duckdb
            return duckdb.sql(query)
        raise ValueError(f"Unsupported backend: {self.backend}")

    def _inject_ctes(self, sql: str, ctes: list[TableSpec]) -> str:
        if not ctes:
            return sql
        parsed = sqlglot.parse_one(sql, dialect="duckdb")
        new_ctes = self._build_cte_exprs(ctes)
        existing_with = parsed.args.get("with_")
        if existing_with:
            existing_with.set("expressions", new_ctes + list(existing_with.expressions))
        else:
            parsed.set("with_", sqlglot_exp.With(expressions=new_ctes))
        return parsed.sql(dialect="duckdb")

    def _build_cte_exprs(self, ctes: list[TableSpec]) -> list:
        exprs = []
        for cte in ctes:
            cte_query = sqlglot.parse_one(cte.sql, dialect="duckdb")
            exprs.append(
                sqlglot_exp.CTE(
                    this=cte_query,
                    alias=sqlglot_exp.TableAlias(
                        this=sqlglot_exp.to_identifier(cte.name),
                    ),
                )
            )
        return exprs
