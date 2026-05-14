UNIT_ABBR = {'week': 'w', 'weeks': 'w', 'month': 'mo', 'months': 'mo',
             'day': 'd', 'days': 'd', 'hour': 'h', 'hours': 'h',
             'year': 'y', 'years': 'y'}


def parse_duration(duration: str) -> tuple[int, str]:
    """'last 7 days' → (7, 'day')   'next 30 days' → (30, 'day')   '7 days' → (7, 'day')"""
    s = duration.strip().removeprefix("last ").removeprefix("next ")
    parts = s.split()
    return int(parts[0]), parts[1].rstrip("s")


def abbr_duration(duration: str) -> str:
    """'last 7 days' → '7d'   'next 30 days' → '30d'"""
    num, unit = parse_duration(duration)
    return f"{num}{UNIT_ABBR.get(unit + 's', unit[0])}"


def _interval_days(s):
    tokens = s.split()
    total = 0
    for i in range(0, len(tokens), 2):
        num = int(tokens[i])
        unit = tokens[i + 1]
        if unit in ("month", "months"):
            total += num * 31
        elif unit in ("week", "weeks"):
            total += num * 7
        elif unit in ("day", "days"):
            total += num
        elif unit in ("hour", "hours"):
            total += num / 24
    return total


def widest_bounds(window_ranges):
    max_lower_days = 0
    max_upper_days = 0
    lower_str = None
    upper_str = None
    has_backward_to_current = False
    min_upper_past_days = float('inf')
    upper_past_str = None

    for start, end in window_ranges:
        if start:
            dur = start.removeprefix("last ").removeprefix("next ")
            days = _interval_days(dur)
            if days > max_lower_days:
                max_lower_days = days
                lower_str = dur
        if not end:
            has_backward_to_current = True
        elif end.startswith("next "):
            dur = end.removeprefix("next ")
            days = _interval_days(dur)
            if days > max_upper_days:
                max_upper_days = days
                upper_str = dur
        elif end.startswith("last "):
            dur = end.removeprefix("last ")
            days = _interval_days(dur)
            if days < min_upper_past_days:
                min_upper_past_days = days
                upper_past_str = dur

    return lower_str, upper_str, has_backward_to_current, upper_past_str


def normalize_window_range(window_range):
    start, end = window_range
    if start and not end and not start.startswith(('last ', 'next ')):
        start = 'last ' + start
    if end and not start and not end.startswith(('last ', 'next ')):
        end = 'next ' + end
    if start and not start.startswith(('last ', 'next ')):
        raise ValueError(
            f"Invalid window range spec {window_range!r}:\n"
            f"start={start!r} should start with 'last' or 'next'. "
            f"E.g. ('last {start}', ...) or ('next {start}', ...)."
        )
    if end and not end.startswith(('last ', 'next ')):
        raise ValueError(
            f"Invalid window range spec {window_range!r}:\n"
            f"end={end!r} should start with 'last' or 'next'. "
            f"E.g. (..., 'last {end}') or (..., 'next {end}')."
        )
    return start, end


def build_window_condition(window_range, date_ref, order_by_col):
    start, end = normalize_window_range(window_range)
    d = order_by_col
    s = date_ref
    if start and not end:
        dur = start.removeprefix("last ")
        return f"{d} >= {s} - INTERVAL '{dur}' AND {d} <= {s}"
    if start and end:
        start_dur = start.removeprefix("last ")
        if end.startswith("last "):
            end_dur = end.removeprefix("last ")
            return f"{d} >= {s} - INTERVAL '{start_dur}' AND {d} <= {s} - INTERVAL '{end_dur}'"
        if end.startswith("next "):
            end_dur = end.removeprefix("next ")
            return f"{d} >= {s} - INTERVAL '{start_dur}' AND {d} <= {s} + INTERVAL '{end_dur}'"
    if not start and end:
        dur = end.removeprefix("next ")
        return f"{d} >= {s} AND {d} <= {s} + INTERVAL '{dur}'"
    raise ValueError(f"Invalid window range spec: {window_range!r}")


def parse_window_range(spec):
    start, end = normalize_window_range(spec)
    def _bound(s):
        if not s:
            return 'current row'
        s = s.strip()
        if s.startswith('last '):
            return f"interval {s.removeprefix('last ')} preceding"
        if s.startswith('next '):
            return f"interval {s.removeprefix('next ')} following"
    return f"range between {_bound(start)} and {_bound(end)}"


def build_window(order_by, partition_by=None, frame=None):
    parts = []
    if partition_by:
        cols = ", ".join(partition_by) if isinstance(partition_by, (list, tuple)) else partition_by
        parts.append(f"PARTITION BY {cols}")
    if order_by:
        parts.append(f"ORDER BY {order_by}")
    if frame:
        parts.append(frame)
    return " ".join(parts)


def window_suffix(spec):
    start, end = spec
    if start and not end:
        return f"last_{abbr_duration(start)}"
    if not start and end:
        return f"next_{abbr_duration(end)}"
    if start and end:
        st = start.removeprefix('last ').removeprefix('next ')
        en = end.removeprefix('last ').removeprefix('next ')
        if start.startswith('last ') and end.startswith('last '):
            return f"{abbr_duration(st)}_ago_to_{abbr_duration(en)}_ago"
        if start.startswith('last ') and end.startswith('next '):
            return f"{abbr_duration(st)}_before_after"
    return ''
