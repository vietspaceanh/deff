import io
import duckdb
from duckdb import read_csv
from deff import sql, Table


def read_md(table: str, dtype: dict | None = None):
    lines = [line.strip() for line in table.strip().splitlines()]
    lines = [l for l in lines if not (all(c in "-| :" for c in l) and "-" in l)]
    lines = [l.strip("|") for l in lines]
    lines = ["|".join(cell.strip() for cell in l.split("|")) for l in lines]
    clean = "\n".join(lines)
    kwargs = {"delimiter": "|", "header": True}
    if dtype:
        kwargs["dtype"] = dtype
    return read_csv(io.StringIO(clean), **kwargs)


def table_from_md(name: str, md: str) -> Table:
    rel = read_md(md)
    duckdb.sql(f"CREATE OR REPLACE TEMP TABLE {name} AS SELECT * FROM rel")
    return sql(f"SELECT * FROM {name}")