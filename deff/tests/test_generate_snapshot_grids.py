import pandas as pd

from deff import sql
from deff.box.snapshots import generate_snapshots
from .utils import read_md, table_from_md


def _snap_from_md(
    md,
    freq="1 day",
    max_inactive="5 days",
    alignment_date="2026-04-01",
):
    data = table_from_md("_grid_input", md)
    return generate_snapshots(
        data,
        "timestamp",
        freq,
        ["customer", "grp"],
        max_inactive=max_inactive,
        alignment_date=alignment_date,
    )


def test_single_transaction():
    snap = _snap_from_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    """)
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_last_bin_longer_inactive():
    snap = _snap_from_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    """, max_inactive="10 days")
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_consecutive_days():
    snap = _snap_from_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-02 00:00:00      | A        | G   |
    | 2026-04-03 00:00:00      | A        | G   |
    """)
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-02 00:00:00      | A        | G   |
    | 2026-04-03 00:00:00      | A        | G   |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_gap_within_inactive_is_filled():
    snap = _snap_from_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-04 00:00:00      | A        | G   |
    """, max_inactive="5 days")
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-02 00:00:00      | A        | G   |
    | 2026-04-03 00:00:00      | A        | G   |
    | 2026-04-04 00:00:00      | A        | G   |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_gap_exceeds_inactive_is_not_filled():
    snap = _snap_from_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-10 00:00:00      | A        | G   |
    """, max_inactive="3 days")
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-02 00:00:00      | A        | G   |
    | 2026-04-03 00:00:00      | A        | G   |
    | 2026-04-10 00:00:00      | A        | G   |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_head_and_tail_has_gap():
    snap = _snap_from_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-10 00:00:00      | A        | G   |
    """, max_inactive="7 days")
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-02 00:00:00      | A        | G   |
    | 2026-04-03 00:00:00      | A        | G   |
    | 2026-04-04 00:00:00      | A        | G   |
    | 2026-04-05 00:00:00      | A        | G   |
    | 2026-04-06 00:00:00      | A        | G   |
    | 2026-04-07 00:00:00      | A        | G   |
    | 2026-04-10 00:00:00      | A        | G   |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_multiple_customers_independent():
    snap = _snap_from_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-03 00:00:00      | A        | G   |
    | 2026-04-02 00:00:00      | B        | G   |
    """)
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-02 00:00:00      | A        | G   |
    | 2026-04-03 00:00:00      | A        | G   |
    | 2026-04-02 00:00:00      | B        | G   |
    | 2026-04-03 00:00:00      | B        | G   |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_different_groups_partitioned():
    snap = _snap_from_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G1  |
    | 2026-04-10 00:00:00      | A        | G1  |
    | 2026-04-03 00:00:00      | A        | G2  |
    """, max_inactive="7 days")
    result = sql(f"FROM {snap} ORDER BY grp, customer, timestamp").df
    expected = read_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G1  |
    | 2026-04-02 00:00:00      | A        | G1  |
    | 2026-04-03 00:00:00      | A        | G1  |
    | 2026-04-04 00:00:00      | A        | G1  |
    | 2026-04-05 00:00:00      | A        | G1  |
    | 2026-04-06 00:00:00      | A        | G1  |
    | 2026-04-07 00:00:00      | A        | G1  |
    | 2026-04-10 00:00:00      | A        | G1  |
    | 2026-04-03 00:00:00      | A        | G2  |
    | 2026-04-04 00:00:00      | A        | G2  |
    | 2026-04-05 00:00:00      | A        | G2  |
    | 2026-04-06 00:00:00      | A        | G2  |
    | 2026-04-07 00:00:00      | A        | G2  |
    | 2026-04-08 00:00:00      | A        | G2  |
    | 2026-04-09 00:00:00      | A        | G2  |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_weekly_freq_projects_forward():
    data = table_from_md("_weekly_input", """
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-16 00:00:00      | A        | G   |
    | 2026-04-16 00:00:00      | B        | G   |
    """)
    snap = generate_snapshots(
        data,
        "timestamp",
        "1 week",
        ["customer", "grp"],
        alignment_date="1970-01-01",
    )
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp           | customer   | grp   |
    |---------------------|------------|-------|
    | 2026-04-02 00:00:00 | A          | G     |
    | 2026-04-09 00:00:00 | A          | G     |
    | 2026-04-16 00:00:00 | A          | G     |
    | 2026-04-16 00:00:00 | B          | G     |
    """).df()
    print(result.to_markdown())
    pd.testing.assert_frame_equal(result, expected)


def test_no_partition_by():
    data = table_from_md("_no_part_input", """
    | timestamp                |
    |--------------------------|
    | 2026-04-01 00:00:00      |
    | 2026-04-05 00:00:00      |
    """)
    snap = generate_snapshots(data, "timestamp", "1 day")
    result = sql(f"FROM {snap} ORDER BY timestamp").df
    expected = read_md("""
    | timestamp                |
    |--------------------------|
    | 2026-04-01 00:00:00      |
    | 2026-04-02 00:00:00      |
    | 2026-04-03 00:00:00      |
    | 2026-04-04 00:00:00      |
    | 2026-04-05 00:00:00      |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_three_bins_gap_in_middle():
    snap = _snap_from_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-06 00:00:00      | A        | G   |
    | 2026-04-07 00:00:00      | A        | G   |
    """, max_inactive="3 days")
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-02 00:00:00      | A        | G   |
    | 2026-04-03 00:00:00      | A        | G   |
    | 2026-04-06 00:00:00      | A        | G   |
    | 2026-04-07 00:00:00      | A        | G   |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_forward_projection_capped_at_global_max():
    data = table_from_md("_cap_input", """
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-04-01 00:00:00      | A        | G   |
    | 2026-04-10 00:00:00      | A        | G   |
    | 2026-04-17 00:00:00      | A        | G   |
    | 2026-04-15 00:00:00      | B        | G   |
    | 2026-04-17 00:00:00      | C        | G   |
    """)
    snap = generate_snapshots(
        data,
        "timestamp",
        "1 week",
        ["customer", "grp"],
        alignment_date="1970-01-01",
    )
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp           | customer   | grp   |
    |---------------------|------------|-------|
    | 2026-04-02 00:00:00 | A          | G     |
    | 2026-04-09 00:00:00 | A          | G     |
    | 2026-04-16 00:00:00 | A          | G     |
    | 2026-04-16 00:00:00 | B          | G     |
    """).df()
    pd.testing.assert_frame_equal(result, expected)


def test_gap_between_grace_period_and_global_max():
    data = table_from_md("_gap_input", """
    | timestamp                | customer | grp |
    |--------------------------|----------|-----|
    | 2026-02-27 00:00:00      | A        | G   |
    | 2026-04-17 00:00:00      | B        | G   |
    """)
    snap = generate_snapshots(
        data,
        "timestamp",
        "1 week",
        ["customer", "grp"],
        alignment_date="1970-01-01",
    )
    result = sql(f"FROM {snap} ORDER BY customer, timestamp").df
    expected = read_md("""
    | timestamp           | customer   | grp   |
    |---------------------|------------|-------|
    | 2026-03-05 00:00:00 | A          | G     |
    | 2026-03-12 00:00:00 | A          | G     |
    | 2026-03-19 00:00:00 | A          | G     |
    | 2026-03-26 00:00:00 | A          | G     |
    | 2026-04-02 00:00:00 | A          | G     |
    """).df()
    pd.testing.assert_frame_equal(result, expected)
