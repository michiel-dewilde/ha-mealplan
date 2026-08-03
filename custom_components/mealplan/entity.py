# SPDX-License-Identifier: GPL-3.0-or-later
"""The base every Meal Plan entity shares."""

from __future__ import annotations

from datetime import date

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import Entity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_UPDATED
from .store import MealPlanStore
from .types import MealPlanConfigEntry


class MealPlanEntity(Entity):
    """Ties an entity to one configured meal plan and its store."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: MealPlanConfigEntry) -> None:
        """Attach to a config entry."""
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Meal Plan",
        )

    @property
    def _store(self) -> MealPlanStore:
        """Return the store behind this entity."""
        return self._entry.runtime_data.store

    @property
    def _today(self) -> date:
        """Return today in the user's own timezone, not the server's."""
        return dt_util.now().date()

    async def _async_persist(self) -> None:
        """Save, redraw, and tell the other entities something changed."""
        self._store.async_schedule_save()
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)
