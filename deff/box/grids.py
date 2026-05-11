from deff import tbl


@tbl
def generate_snapshot_grids(
    table,
    timestamp_col: str,
    partition_by_cols: list[str],
    freq: str,
    max_inactive=None,
    alignment_date="1970-01-01 00:00:00",
):
    freq_value, freq_unit = int(freq.split(None, 1)[0]), freq.split(None, 1)[1].strip()
    inactive_str = max_inactive or f"{5 * freq_value} {freq_unit}"
    partition_expr = ", ".join(partition_by_cols)

    @tbl
    def binned():
        seconds_per = {
            "hour": 3600, "hours": 3600,
            "day": 86400, "days": 86400,
            "week": 604800, "weeks": 604800,
        }
        if freq_unit in seconds_per:
            scale = seconds_per[freq_unit] * freq_value
            raw_diff = f"EXTRACT(epoch FROM {timestamp_col}::TIMESTAMP - '{alignment_date}'::TIMESTAMP)"
            delta = f"((FLOOR({raw_diff} / {scale}) * {freq_value})::VARCHAR || ' {freq_unit}')::INTERVAL"
        else:
            raw_diff = f"DATEDIFF('month', '{alignment_date}'::TIMESTAMP, {timestamp_col}::TIMESTAMP)::DOUBLE"
            delta = f"((FLOOR({raw_diff} / {freq_value}) * {freq_value})::VARCHAR || ' months')::INTERVAL"

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
