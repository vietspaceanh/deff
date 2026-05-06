from __future__ import annotations

import pandas as pd

from .base import Result


class DuckDBResult(Result):
    def __init__(self, relation):
        self._relation = relation

    def df(self) -> pd.DataFrame:
        if self._relation is None:
            return pd.DataFrame()
        return self._relation.df()

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

    def fetchall(self) -> list[tuple]:
        if self._relation is None:
            return []
        return self._relation.fetchall()

    def fetchmany(self, n: int) -> list[tuple]:
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
