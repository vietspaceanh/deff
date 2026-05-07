from __future__ import annotations

import duckdb

from .base import Result


class DuckDBResult(Result):
    def __init__(self, query):
        self._query = query
        self._relation = duckdb.sql(query)

    @property
    def columns(self) -> list[str]:
        if self._relation is None:
            return []
        return self._relation.columns

    @property
    def types(self) -> list[str]:
        if self._relation is None:
            return []
        return [str(t).upper().split("(")[0] for t in self._relation.types]

    def df(self):
        import pandas as pd
        rel = duckdb.sql(self._query)
        if rel is None:
            return pd.DataFrame()
        return rel.df()

    def fetchall(self) -> list[tuple]:
        if self._relation is None:
            return []
        return self._relation.fetchall()

    def fetchmany(self, n: int, fresh: bool = False) -> list[tuple]:
        if fresh:
            rel = duckdb.sql(self._query)
            if rel is None:
                return []
            return rel.fetchmany(n)
        if self._relation is None:
            return []
        return self._relation.fetchmany(n)

    def fetchone(self) -> tuple | None:
        if self._relation is None:
            return None
        return self._relation.fetchone()

    def __iter__(self):
        if self._relation is None:
            return
        while True:
            row = self._relation.fetchone()
            if row is None:
                break
            yield row

    def __len__(self) -> int:
        if self._relation is None:
            return 0
        return self._relation.shape[0]
