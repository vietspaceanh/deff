from deff import tbl, Table
from .common import get_aggs

_ALIAS_BASE = "base"
_ALIAS_LOOKUP = "lookup"


@tbl
def lookup_aggregate(
    base: Table,
    lookup: Table,
    partition_by: list[str] | None = None,
    order_by: str | None = None,
    *,
    stats: list[tuple[str, str]],
    window_ranges: list[tuple[str, str]] | None = None,
):
    if order_by is None:
        snap_ob = tx_ob = None
    elif isinstance(order_by, str):
        snap_ob = tx_ob = order_by
    else:
        snap_ob, tx_ob = order_by

    if order_by and window_ranges:
        return lateral_join_lookup(
            base, lookup,
            partition_by, snap_ob, tx_ob,
            stats, window_ranges,
        )

    if not partition_by:
        raise ValueError("partition_by is required when no window_ranges are specified")

    return groupby_lookup(
        base, lookup,
        partition_by, stats,
    )


def lateral_join_lookup(
    base,
    lookup,
    partition_by,
    snap_ob,
    tx_ob,
    stats,
    window_ranges,
):
    aggs = get_aggs(stats, window_ranges)
    select, where = aggs.as_lateral(partition_by, snap_ob, _ALIAS_BASE, _ALIAS_LOOKUP)
    inner_select = "\n".join(f"{line}" for line in select.split("\n"))

    partition_cols = ", ".join(partition_by) if partition_by else None
    partition_col_parts = ", ".join(
        f"{_ALIAS_BASE}.{col}" for col in partition_by or []
    )

    distinct_cols = ", ".join([snap_ob] + (partition_by or []))

    order_clause = f"{partition_cols}, {tx_ob}" if partition_cols else tx_ob
    select_cols = (
        f"{_ALIAS_BASE}.{snap_ob},\n{partition_col_parts},"
        if partition_col_parts
        else f"{_ALIAS_BASE}.{snap_ob},"
    )

    return f"""--sql
    WITH _src AS (
        SELECT * FROM {lookup}
        ORDER BY {order_clause}
    )
    SELECT
        {select_cols}
        w.*
    FROM (SELECT DISTINCT {distinct_cols} FROM {base}) {_ALIAS_BASE}
    LEFT JOIN LATERAL (
        SELECT
        {inner_select}
        FROM _src {_ALIAS_LOOKUP}
        {where}
    ) w ON true
    """


def groupby_lookup(
    base,
    lookup,
    partition_by,
    stats,
):
    select_parts = []
    group_parts = []
    for col in partition_by:
        select_parts.append(f"{_ALIAS_BASE}.{col}")
        group_parts.append(f"{_ALIAS_BASE}.{col}")
    for formula, alias in stats:
        if alias:
            select_parts.append(f'{formula} AS "{alias}"')
        else:
            select_parts.append(f"{formula}")

    on_conds = [f"{_ALIAS_LOOKUP}.{col} = {_ALIAS_BASE}.{col}" for col in partition_by]

    return f"""--sql
    SELECT
        {',\n'.join(select_parts)}
    FROM {base} {_ALIAS_BASE}
        LEFT JOIN {lookup} {_ALIAS_LOOKUP}
        ON {' AND '.join(on_conds)}
    GROUP BY {', '.join(group_parts)}
    """
