from deff import tbl, Table


@tbl
def generate_snapshot_grids(
    table: Table,
    timestamp_col: str,
    freq: str,
    partition_by_cols: list[str] | None = None,
    max_inactive=None,
    alignment_date="1970-01-01 00:00:00",
):
    freq_value, freq_unit = int(freq.split(None, 1)[0]), freq.split(None, 1)[1].strip()
    seconds_per = {
        "hour": 3600, "hours": 3600,
        "day": 86400, "days": 86400,
        "week": 604800, "weeks": 604800,
    }

    if not partition_by_cols:
        min_delta, _ = _delta_expr(f"MIN({timestamp_col})", freq_value, freq_unit, alignment_date, seconds_per)
        max_delta, _ = _delta_expr(f"MAX({timestamp_col})", freq_value, freq_unit, alignment_date, seconds_per)
        return f"""--sql
        WITH bounds AS (
            SELECT '{alignment_date}'::TIMESTAMP + {min_delta} AS start_ts,
                   '{alignment_date}'::TIMESTAMP + {max_delta} AS end_ts
            FROM {table}
        )
        SELECT UNNEST(generate_series(start_ts, end_ts, INTERVAL '{freq}')) AS {timestamp_col}
        FROM bounds
        """

    inactive_str = max_inactive or f"{5 * freq_value} {freq_unit}"
    partition_expr = ", ".join(partition_by_cols)

    @tbl
    def binned():
        delta, raw_diff = _delta_expr(timestamp_col, freq_value, freq_unit, alignment_date, seconds_per)
        return f"""--sql
        WITH bin_prep AS (
            SELECT *, {raw_diff} AS raw_diff
            FROM {table}
        )
        SELECT DISTINCT {partition_expr},
            '{alignment_date}'::TIMESTAMP + {delta} AS binned_ts
        FROM bin_prep
        """

    return f"""--sql
    WITH with_next AS (
        FROM {binned}
        SELECT *,
            LEAD(binned_ts) OVER (PARTITION BY {partition_expr} ORDER BY binned_ts) AS next_bin,
            LEAST(
                LEAD(binned_ts) OVER (PARTITION BY {partition_expr} ORDER BY binned_ts),
                binned_ts + INTERVAL '{inactive_str}'
            ) AS upper_bound
    )
    FROM with_next
    SELECT
        unnest(generate_series(
            binned_ts,
            GREATEST(upper_bound - INTERVAL '{freq}', binned_ts),
            INTERVAL '{freq}'
        )) AS {timestamp_col},
        {partition_expr},
    WHERE next_bin IS NOT NULL
    ORDER BY {partition_expr}, {timestamp_col}
    """


def _delta_expr(ts_expr, freq_value, freq_unit, alignment_date, seconds_per):
    if freq_unit in seconds_per:
        scale = seconds_per[freq_unit] * freq_value
        raw = f"EXTRACT(epoch FROM {ts_expr}::TIMESTAMP - '{alignment_date}'::TIMESTAMP)"
        return f"((FLOOR({raw} / {scale}) * {freq_value})::VARCHAR || ' {freq_unit}')::INTERVAL", raw
    raw = f"DATEDIFF('month', '{alignment_date}'::TIMESTAMP, {ts_expr}::TIMESTAMP)::DOUBLE"
    return f"((FLOOR({raw} / {freq_value}) * {freq_value})::VARCHAR || ' months')::INTERVAL", raw