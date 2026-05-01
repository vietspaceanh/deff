from __future__ import annotations

import pandas as pd

from .base import Result


class DuckDBResult(Result):
    def __init__(self, relation):
        self._relation = relation
        self._cache = None

    def _get_cache(self):
        if self._cache is None:
            self._cache = self._relation.fetchall()
        return self._cache

    def df(self) -> pd.DataFrame:
        return self._relation.df()

    @property
    def columns(self) -> list[str]:
        return self._relation.columns

    @property
    def types(self) -> list[str]:
        return [str(t).upper().split("(")[0] for t in self._relation.types]

    def fetchall(self) -> list[tuple]:
        return list(self._get_cache())

    def fetchmany(self, n: int) -> list[tuple]:
        return self._get_cache()[:n]

    def fetchone(self) -> tuple | None:
        rows = self._get_cache()
        return rows[0] if rows else None

    def __iter__(self):
        return iter(self._get_cache())

    def __len__(self) -> int:
        return len(self._get_cache())
