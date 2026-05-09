from .window import build_window_condition, parse_window_range, window_suffix, widest_bounds


class AggregationSpecs:
    def __init__(self, stats, window_ranges=None):
        self.stats = stats
        self.window_ranges = window_ranges

    def as_plain(self):
        parts = []
        for formula, alias in self.stats:
            if alias:
                parts.append(f'{formula} AS "{alias}"')
            else:
                parts.append(formula)
        return ",\n".join(parts)

    def as_window(self, partition_by, order_by):
        if not self.window_ranges:
            raise ValueError("window_ranges required for as_window")
        parts = []
        for formula, alias in self.stats:
            for wr in self.window_ranges:
                over = (
                    f"partition by {','.join(partition_by)} " if partition_by else ""
                )
                over += f"order by {order_by} " if order_by else ""
                suffix = window_suffix(wr)
                full_alias = f"{alias}_{suffix}" if alias else suffix
                parts.append(
                    f'{formula} over ( {over}{parse_window_range(wr)} ) AS "{full_alias}"'
                )
        return ",\n".join(parts)

    def as_filtered(self, order_by, ref):
        if not self.window_ranges:
            raise ValueError("window_ranges required for as_filtered")
        return self._build_filter_exprs(f"TIMESTAMP '{ref}'", order_by)

    def as_lateral(self, partition_by, order_by, left_tbl="snapshots", right_tbl="transactions"):
        if not self.window_ranges:
            raise ValueError("window_ranges required for as_lateral")

        select = self._build_filter_exprs(f"{left_tbl}.{order_by}", f"{right_tbl}.{order_by}")

        where = [f"{right_tbl}.{col} = {left_tbl}.{col}" for col in partition_by]
        where.extend(self._build_widest_conds(f"{left_tbl}.{order_by}", f"{right_tbl}.{order_by}"))
        where_str = f"WHERE {where[0]}" + "".join(
            f"\nAND {c}" for c in where[1:]
        ) if where else ""

        return select, where_str

    def _build_filter_exprs(self, date_ref, order_by_col):
        parts = []
        for formula, alias in self.stats:
            for wr in self.window_ranges:
                cond = build_window_condition(wr, date_ref, order_by_col)
                suffix = window_suffix(wr)
                full_alias = f"{alias}_{suffix}" if alias else suffix
                parts.append(f'{formula} FILTER (WHERE {cond}) AS "{full_alias}"')
        return ",\n".join(parts)

    def _build_widest_conds(self, left_col, right_col):
        lower_str, upper_str, has_backward = widest_bounds(self.window_ranges)
        conds = []
        if lower_str:
            conds.append(f"{right_col} >= {left_col} - INTERVAL '{lower_str}'")
        if upper_str:
            conds.append(f"{right_col} <= {left_col} + INTERVAL '{upper_str}'")
        elif has_backward:
            conds.append(f"{right_col} <= {left_col}")
        return conds


def get_aggs(stats, window_ranges=None):
    return AggregationSpecs(stats, window_ranges)
