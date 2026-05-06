from __future__ import annotations

from .base import Result
from .. import config as global_config


class Runner:
    def __init__(self, dialect: str | None = None):
        self.dialect = dialect if dialect is not None else global_config.dialect

    def sql(self, query: str) -> Result:
        if self.dialect == "duckdb":
            import duckdb
            from .duckdb import DuckDBResult
            if global_config.memory_limit:
                duckdb.sql(f"SET memory_limit = '{global_config.memory_limit}'")
            return DuckDBResult(duckdb.sql(query))
        if self.dialect == "spark":
            from pyspark.sql import SparkSession
            from .spark import SparkResult
            spark = SparkSession.builder.getOrCreate()
            return SparkResult(spark.sql(query))
        raise ValueError(f"Unsupported backend: {self.dialect}")
