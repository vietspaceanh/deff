from __future__ import annotations

import duckdb

from .base import Result


class DuckDBResult(Result):
    def __init__(self, query):
        self.query = query
        
    @property
    def relation(self):
        return duckdb.sql(self.query)

    @property
    def columns(self) -> list[str]:
        if self.relation is None:
            return []
        return self.relation.columns

    @property
    def types(self) -> list[str]:
        if self.relation is None:
            return []
        return [str(t).upper().split("(")[0] for t in self.relation.types]

    def df(self):
        import pandas as pd
        if self.relation is None:
            return pd.DataFrame()
        return self.relation.df()

    def fetchall(self) -> list[tuple]:
        if self.relation is None:
            return []
        return self.relation.fetchall()

    def fetchmany(self, n: int) -> list[tuple]:
        if self.relation is None:
            return []
        return self.relation.fetchmany(n)

    def fetchone(self) -> tuple | None:
        if self.relation is None:
            return None
        return self.relation.fetchone()

    def __iter__(self):
        if self.relation is None:
            return
        while True:
            row = self.relation.fetchone()
            if row is None:
                break
            yield row

    def __len__(self) -> int:
        if self.relation is None:
            return 0
        return self.relation.shape[0]
