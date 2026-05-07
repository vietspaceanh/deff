from __future__ import annotations

from pyspark.sql import SparkSession
from .base import Result


class SparkResult(Result):
    def __init__(self, query):
        self._df = SparkSession.builder.getOrCreate().sql(query)

    def df(self):
        return self._df.toPandas()

    @property
    def columns(self) -> list[str]:
        return self._df.columns

    @property
    def types(self) -> list[str]:
        return [t.upper().split("(")[0] for _, t in self._df.dtypes]

    def fetchall(self) -> list[tuple]:
        return [tuple(row) for row in self._df.collect()]

    def fetchmany(self, n: int, fresh: bool = False) -> list[tuple]:
        return [tuple(row) for row in self._df.limit(n).collect()]

    def fetchone(self) -> tuple | None:
        rows = self._df.limit(1).collect()
        if not rows:
            return None
        return tuple(rows[0])

    def __iter__(self):
        return iter(self.fetchall())

    def __len__(self) -> int:
        return self._df.count()
