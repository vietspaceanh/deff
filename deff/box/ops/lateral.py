from deff import tbl
from ..common import get_aggs


@tbl
def lookup_aggregate(
    snapshots,
    transactions,
    partition_by: list[str],
    order_by: str,
    stats: list[tuple[str, str]],
    window_ranges: list[tuple[str, str]],
    snapshot_alias="snapshots",
    transactions_alias="transactions"
):
    if order_by is None:
        snap_ob = tx_ob = None
    elif isinstance(order_by, str):
        snap_ob = tx_ob = order_by
    else:
        snap_ob, tx_ob = order_by

    if order_by and window_ranges:
        aggs = get_aggs(stats, window_ranges)
        select, where = aggs.as_lateral(partition_by, order_by, snapshot_alias, transactions_alias)
        inner_select = "\n".join(f"{line}" for line in select.split("\n"))

        partition_cols = ", ".join(partition_by)
        partition_col_parts = ", ".join(
            f"{snapshot_alias}.{col}" for col in partition_by
        )

        return f"""--sql
        WITH _src AS (
            SELECT * FROM {transactions}
            ORDER BY {partition_cols}, {tx_ob}
        )
        SELECT
            {snapshot_alias}.{snap_ob},
            {partition_col_parts},
            w.*
        FROM {snapshots} {snapshot_alias}
        LEFT JOIN LATERAL (
            SELECT
            {inner_select}
            FROM _src {transactions_alias}
            {where}
        ) w ON true
        """
    else:
        select_parts = []
        group_parts = []
        if order_by:
            select_parts.append(f"{snapshot_alias}.{snap_ob}")
            group_parts.append(f"{snapshot_alias}.{snap_ob}")
        for col in partition_by:
            select_parts.append(f"{snapshot_alias}.{col}")
            group_parts.append(f"{snapshot_alias}.{col}")
        for formula, alias in stats:
            if alias:
                select_parts.append(f'{formula} AS "{alias}"')
            else:
                select_parts.append(f"{formula}")

        on_conds = [f"{transactions_alias}.{col} = {snapshot_alias}.{col}" for col in partition_by]
        on_clause = " AND ".join(on_conds) if on_conds else "true"

        return f"""--sql
        SELECT
            {',\n'.join(select_parts)}
        FROM {snapshots} {snapshot_alias}
            LEFT JOIN {transactions} {transactions_alias}
            ON {on_clause}
        GROUP BY {', '.join(group_parts)}
        """
