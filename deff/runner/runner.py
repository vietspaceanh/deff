from __future__ import annotations

from .base import Result
from .. import config as global_config


class Runner:
    def __init__(self, dialect: str | None = None):
        self.dialect = dialect if dialect is not None else global_config.dialect

    def sql(self, query: str) -> Result:
        if self.dialect == "duckdb":
            from .duckdb import DuckDBResult, set_config

            set_config()
            return DuckDBResult(query)

        if self.dialect == "spark":
            from .spark import SparkResult

            return SparkResult(query)

        raise ValueError(f"Unsupported backend: {self.dialect}")
