from __future__ import annotations

from sqlglot.parsers.duckdb import DuckDBParser

_parse_table_original = DuckDBParser._parse_table


def _parse_table_patched(self, **kwargs):
    wants_joins = kwargs.pop("joins", False)
    table = _parse_table_original(self, **{**kwargs, "joins": False})
    if wants_joins and table is not None:
        for join in self._parse_joins():
            table.append("joins", join)
    return table


DuckDBParser._parse_table = _parse_table_patched

dialect: str = "duckdb"
rows: int = 200
