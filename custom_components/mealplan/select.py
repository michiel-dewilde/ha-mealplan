# SPDX-License-Identifier: GPL-3.0-or-later
"""Which store you are shopping at.

Store names are content, not interface: supermarket chains are regional, and a
fixed list would be wrong almost everywhere. The options are whatever stores
this installation knows about, seeded or added.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import SIGNAL_UPDATED
from .entity import MealPlanEntity
from .types import MealPlanConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MealPlanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the store selector."""
    async_add_entities([StoreSelect(entry)])


class StoreSelect(MealPlanEntity, SelectEntity, RestoreEntity):
    """Selects the store whose walking route the list is sorted into."""

    _attr_translation_key = "store"

    def __init__(self, entry: MealPlanConfigEntry) -> None:
        """Set up the selector."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_store"
        self._selected: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last choice and listen for new stores appearing."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and last.state in self.options:
            self._selected = last.state
        self._entry.runtime_data.store_choice = self.current_option
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        """Redraw when the set of known stores changed."""
        self._entry.runtime_data.store_choice = self.current_option
        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        """Return the stores this installation knows about."""
        return sorted(self._store.data.stores)

    @property
    def current_option(self) -> str | None:
        """Return the selected store, defaulting to the only one if there is only one."""
        options = self.options
        if self._selected in options:
            return self._selected
        return options[0] if len(options) == 1 else None

    async def async_select_option(self, option: str) -> None:
        """Pick a store."""
        self._selected = option
        self._entry.runtime_data.store_choice = option
        self.async_write_ha_state()
