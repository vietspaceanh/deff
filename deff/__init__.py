from __future__ import annotations

from . import config
from .decorator import tbl, params
from .table import Table, sql
from .runtime import runtime
from .theme import ThemeConfig as DeffThemeConfig, ThemeService as DeffThemeService, deff_theme

set_theme = deff_theme.use
