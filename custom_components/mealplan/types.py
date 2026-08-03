# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared types.

Separate from `__init__.py` so platforms can import the config entry type
without importing the set-up code, which would import them right back.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .store import MealPlanStore


@dataclass(slots=True)
class MealPlanRuntimeData:
    """What one configured meal plan carries while it is loaded."""

    store: MealPlanStore

    store_choice: str | None = None
    """The store currently selected, kept here so services need not look up the entity."""


type MealPlanConfigEntry = ConfigEntry[MealPlanRuntimeData]
