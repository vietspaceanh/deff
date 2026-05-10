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

    for start, end in window_ranges:
        if start:
            dur = start.removeprefix("last ").removeprefix("next ")
            days = _interval_days(dur)
            if days > max_lower_days:
                max_lower_days = days
                lower_str = dur
        if not end:
            has_backward_to_current = True
        if end and end.startswith("next "):
            dur = end.removeprefix("next ")
            days = _interval_days(dur)
            if days > max_upper_days:
                max_upper_days = days
                upper_str = dur

    return lower_str, upper_str, has_backward_to_current


def build_window_condition(window_range, date_ref, order_by_col):
    start, end = window_range
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
    def _bound(s):
        if not s:
            return 'current row'
        s = s.strip()
        if s.startswith('last '):
            return f"interval {s.removeprefix('last ')} preceding"
        if s.startswith('next '):
            return f"interval {s.removeprefix('next ')} following"
        raise ValueError(f"bound must start with 'last ' or 'next ', or be empty: got {s!r}")
    start, end = spec
    return f"range between {_bound(start)} and {_bound(end)}"


def window_suffix(spec):
    UNIT_ABBR = {'week': 'w', 'weeks': 'w', 'month': 'mo', 'months': 'mo',
                 'day': 'd', 'days': 'd', 'hour': 'h', 'hours': 'h',
                 'year': 'y', 'years': 'y'}

    def _abbr(s):
        tokens = s.strip().split()
        parts = []
        for i in range(0, len(tokens), 2):
            num = tokens[i]
            unit = tokens[i + 1]
            if num != "0":
                parts.append(f"{num}{UNIT_ABBR.get(unit, unit[0])}")
        return "_".join(parts)

    start, end = spec
    if start and not end:
        return f"last_{_abbr(start.removeprefix('last '))}"
    if not start and end:
        return f"next_{_abbr(end.removeprefix('next '))}"
    if start and end:
        st = start.removeprefix('last ').removeprefix('next ')
        en = end.removeprefix('last ').removeprefix('next ')
        if start.startswith('last ') and end.startswith('last '):
            return f"{_abbr(st)}_ago_to_{_abbr(en)}_ago"
        if start.startswith('last ') and end.startswith('next '):
            return f"{_abbr(st)}_before_after"
    return ''
