from __future__ import annotations

import os
from dataclasses import dataclass, field


TYPE_PROXY = {
    "numeric": "blue",
    "string": "green",
    "boolean": "orange",
    "temporal": "purple",
}

UI_PROXY = {
    "badge_bg": "surface0",
    "border": "surface1",
    "default": "gray",
}


@dataclass
class ThemeConfig:
    name: str
    mode: str
    proxy: dict = field(default_factory=dict)


PRESET_FACTORIES = {
    "dark": lambda: ThemeConfig(
        name="dark", mode="dark",
        proxy={
            "blue": "#89b4fa", "green": "#8ee087", "orange": "#fab387",
            "purple": "#b4befe", "red": "#f38ba8", "teal": "#94e2d5",
            "yellow": "#f9e2af", "pink": "#f5c2e7",
            "gray": "#555555",
            "surface0": "#313244", "surface1": "#45475a", "surface2": "#585b70",
        },
    ),
    "light": lambda: ThemeConfig(
        name="light", mode="light",
        proxy={
            "blue": "#1c4ed8", "green": "#2d7a1e", "orange": "#d95b0a",
            "purple": "#6d28d9", "red": "#d20f39", "teal": "#179299",
            "yellow": "#df8e1d", "pink": "#ea76cb",
            "gray": "#4f5368",
            "surface0": "#d0d4dd", "surface1": "#d0d4dd", "surface2": "#acb0be",
        },
    ),
    "auto": lambda: _auto_config(),
}


def _auto_config() -> ThemeConfig:
    colorfgbg = os.environ.get("COLORFGBG", "")
    if colorfgbg.endswith(";0"):
        return PRESET_FACTORIES["dark"]()
    if colorfgbg.endswith(";15"):
        return PRESET_FACTORIES["light"]()
    if os.environ.get("DARK_BACKGROUND") == "1":
        return PRESET_FACTORIES["dark"]()
    return PRESET_FACTORIES["dark"]()


class ThemeService:
    def __init__(self):
        self._config = PRESET_FACTORIES["auto"]()

    @property
    def config(self) -> ThemeConfig:
        return self._config

    def use(self, preset_or_config: str | ThemeConfig | None = None, /, **overrides) -> None:
        if preset_or_config is None:
            pass
        elif isinstance(preset_or_config, str):
            factory = PRESET_FACTORIES.get(preset_or_config)
            if factory is None:
                raise ValueError(
                    f"Unknown theme: {preset_or_config!r}. "
                    f"Available: {list(PRESET_FACTORIES)}"
                )
            self._config = factory()
        elif isinstance(preset_or_config, ThemeConfig):
            self._config = preset_or_config
        else:
            raise TypeError(
                f"Expected str, ThemeConfig, or None, got {type(preset_or_config).__name__}"
            )

        proxy = overrides.pop("proxy", None)
        mode = overrides.pop("mode", None)
        name = overrides.pop("name", None)

        if proxy is not None:
            self._config.proxy = proxy
        if mode is not None:
            self._config.mode = mode
        if name is not None:
            self._config.name = name

        if overrides:
            raise TypeError(f"Unexpected overrides: {list(overrides)}")

    def reset(self) -> None:
        self.use("auto")


deff_theme = ThemeService()


def resolve_colors() -> dict[str, str]:
    cfg = deff_theme.config
    p = cfg.proxy
    if not p:
        return {}
    type_colors = {}
    for type_name, proxy_name in TYPE_PROXY.items():
        type_colors[type_name] = p.get(proxy_name, "#888888")
    ui_colors = {}
    for ui_name, proxy_name in UI_PROXY.items():
        ui_colors[ui_name] = p.get(proxy_name, "#888888")
    blue = p.get("blue", "#888888")
    ui_colors["highlighted_border"] = blue + "b8"
    return type_colors | ui_colors
