UNIT_ABBR = {'week': 'w', 'weeks': 'w', 'month': 'mo', 'months': 'mo',
             'day': 'd', 'days': 'd', 'hour': 'h', 'hours': 'h',
             'year': 'y', 'years': 'y',
             'quarter': 'q', 'quarters': 'q',
             'minute': 'min', 'minutes': 'min',
             'second': 's', 'seconds': 's',
             'millisecond': 'ms', 'milliseconds': 'ms'}


def parse_duration(duration: str) -> tuple[int, str]:
    """'last 7 days' → (7, 'day')   'next 30 days' → (30, 'day')   '7 days' → (7, 'day')"""
    s = duration.strip().removeprefix("last ").removeprefix("next ")
    parts = s.split()
    return int(parts[0]), parts[1].rstrip("s")


def abbr_duration(duration: str) -> str:
    """'last 7 days' → '7d'   '3 months 1 week' → '3mo_1w'"""
    s = duration.strip().removeprefix("last ").removeprefix("next ")
    parts = s.split()
    abbrs = []
    for i in range(0, len(parts), 2):
        num = parts[i]
        unit = parts[i + 1].rstrip("s")
        abbrs.append(f"{num}{UNIT_ABBR.get(unit + 's', unit[0])}")
    return "_".join(abbrs)


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


def build_window_condition(window_range, date_ref, order_by_col):
    start, end = _normalize_window_range(window_range)
    d = order_by_col
    s = date_ref
    if start and not end:
        dur = start.removeprefix('last ').removeprefix('next ')
        return f"{d} >= {s} {_op(start)} INTERVAL '{dur}' AND {d} <= {s}"
    if start and end:
        start_dur = start.removeprefix('last ').removeprefix('next ')
        end_dur = end.removeprefix('last ').removeprefix('next ')
        return (
            f"{d} >= {s} {_op(start)} INTERVAL '{start_dur}'"
            f" AND {d} <= {s} {_op(end)} INTERVAL '{end_dur}'"
        )
    if not start and end:
        dur = end.removeprefix('last ').removeprefix('next ')
        return f"{d} >= {s} AND {d} <= {s} {_op(end)} INTERVAL '{dur}'"
    raise ValueError(f"Invalid window range spec: {window_range!r}")


def parse_window_range(spec):
    start, end = _normalize_window_range(spec)
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
    start, end = _normalize_window_range(spec)
    if not start and not end:
        raise ValueError(f"Invalid window range spec: {spec!r}")
    if start and not end:
        tag = 'last' if start.startswith('last ') else 'next'
        return f"{tag}_{abbr_duration(start)}"
    if not start and end:
        tag = 'next' if end.startswith('next ') else 'last'
        return f"{tag}_{abbr_duration(end)}"
    if start and end:
        st = start.removeprefix('last ').removeprefix('next ')
        en = end.removeprefix('last ').removeprefix('next ')
        if start.startswith('last ') and end.startswith('last '):
            return f"{abbr_duration(st)}_ago_to_{abbr_duration(en)}_ago"
        if start.startswith('last ') and end.startswith('next '):
            return f"{abbr_duration(st)}_ago_to_{abbr_duration(en)}_ahead"
        if start.startswith('next ') and end.startswith('next '):
            return f"{abbr_duration(st)}_ahead_to_{abbr_duration(en)}_ahead"
    return ''


def _op(s):
    return '-' if s.startswith('last ') else '+'


def _interval_days(s):
    tokens = s.split()
    total = 0
    for i in range(0, len(tokens), 2):
        num = int(tokens[i])
        unit = tokens[i + 1]
        if unit in ("month", "months"):
            total += num * 31
        elif unit in ("quarter", "quarters"):
            total += num * 3 * 31
        elif unit in ("week", "weeks"):
            total += num * 7
        elif unit in ("day", "days"):
            total += num
        elif unit in ("hour", "hours"):
            total += num / 24
        elif unit in ("minute", "minutes"):
            total += num / 1440
        elif unit in ("second", "seconds"):
            total += num / 86400
        elif unit in ("millisecond", "milliseconds"):
            total += num / 86400000
    return total


def _normalize_window_range(window_range):
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
    if start and end and start.startswith('next ') and end.startswith('last '):
        raise ValueError(
            f"Invalid window range spec {window_range!r}:\n"
            f"start='next ...' with end='last ...' produces an empty range. "
            f"Use ('next A', 'next B') or ('last A', 'last B') or ('last A', 'next B')."
        )
    return start, end