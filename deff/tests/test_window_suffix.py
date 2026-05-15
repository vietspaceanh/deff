import pytest
from deff.box.common.window import window_suffix


@pytest.mark.parametrize('spec, expected', [
    (('last 7 days', None), 'last_7d'),
    ((None, 'next 30 days'), 'next_30d'),
    (('7 days', None), 'last_7d'),
    ((None, '30 days'), 'next_30d'),
    (('last 7 days', ''), 'last_7d'),
    (('last 3 months', 'last 1 month'), '3mo_ago_to_1mo_ago'),
    (('last 3 months 1 week', 'last 3 months'), '3mo_1w_ago_to_3mo_ago'),
    (('next 1 month', 'next 3 months'), '1mo_ahead_to_3mo_ahead'),
    (('last 7 days', 'next 7 days'), '7d_ago_to_7d_ahead'),
    (('last 2 quarters', 'last 1 quarter'), '2q_ago_to_1q_ago'),
    (('last 30 minutes', 'last 5 minutes'), '30min_ago_to_5min_ago'),
    (('last 30 seconds', 'last 10 seconds'), '30s_ago_to_10s_ago'),
    (('last 500 milliseconds', 'last 100 milliseconds'), '500ms_ago_to_100ms_ago'),
    (('last 1 day 2 hours', 'last 1 day'), '1d_2h_ago_to_1d_ago'),
    (('last 1 day', 'next 3 hours'), '1d_ago_to_3h_ahead'),
    (('last 2 quarters 1 month', 'last 1 quarter'), '2q_1mo_ago_to_1q_ago'),
    (('last 1 quarter 1 month 2 weeks', 'last 1 quarter'), '1q_1mo_2w_ago_to_1q_ago'),
    (('last 3 months 1 week 2 days', 'last 3 months'), '3mo_1w_2d_ago_to_3mo_ago'),
])
def test_window_suffix(spec, expected):
    assert window_suffix(spec) == expected


@pytest.mark.parametrize('spec', [
    (None, None),
    ('', ''),
])
def test_window_suffix_invalid(spec):
    with pytest.raises(ValueError):
        window_suffix(spec)
