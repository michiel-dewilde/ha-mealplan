# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading the config entry options into something typed."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_CALENDARS,
    CONF_MENU_DAYS,
    CONF_ROLLOVER_DAY,
    CONF_UNDATED_STOCK,
    CONF_WEEK_START,
    DEFAULT_MENU_DAYS,
    DEFAULT_ROLLOVER_DAY,
    DEFAULT_UNDATED_STOCK,
    DEFAULT_WEEK_START,
    MAX_MENU_DAYS,
    MIN_MENU_DAYS,
)


@dataclass(frozen=True, slots=True)
class PlanOptions:
    """The planning settings of one config entry."""

    calendars: tuple[str, ...]
    week_start: str
    menu_days: int
    rollover_day: str
    undated_stock: bool


def plan_options(entry: ConfigEntry) -> PlanOptions:
    """Read the options off a config entry, with the defaults filled in."""
    options = entry.options
    menu_days = int(options.get(CONF_MENU_DAYS, DEFAULT_MENU_DAYS))
    return PlanOptions(
        calendars=tuple(options.get(CONF_CALENDARS) or ()),
        week_start=str(options.get(CONF_WEEK_START, DEFAULT_WEEK_START)),
        menu_days=min(max(menu_days, MIN_MENU_DAYS), MAX_MENU_DAYS),
        rollover_day=str(options.get(CONF_ROLLOVER_DAY, DEFAULT_ROLLOVER_DAY)),
        undated_stock=bool(options.get(CONF_UNDATED_STOCK, DEFAULT_UNDATED_STOCK)),
    )
