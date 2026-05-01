from __future__ import annotations

from .base import Result
from .duckdb import DuckDBResult
from .spark import SparkResult
from .runner import Runner

__all__ = ["Result", "DuckDBResult", "SparkResult", "Runner"]
