# SPDX-License-Identifier: GPL-3.0-or-later
"""Which store you are shopping at.

Store names are content, not interface: supermarket chains are regional, and a
fixed list would be wrong almost everywhere. The options are whatever stores
this installation knows about, seeded or added.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import SIGNAL_UPDATED, ListName
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
        """Return the stores this installation knows about, most recently shopped first.

        This is a list you grab from at the door of a shop, not one you look
        something up in, so the shop you were in last week comes before the one
        whose name starts with an A. Stores nobody has bought anything at yet
        fall to the back, in alphabetical order among themselves.
        """
        store = self._store
        alphabetical = sorted(store.data.stores)
        return sorted(
            alphabetical,
            key=lambda name: last.toordinal() if (last := store.last_shopped(name)) else 0,
            reverse=True,
        )

    @property
    def current_option(self) -> str | None:
        """Return the selected store, defaulting to the only one if there is only one."""
        options = self.options
        if self._selected in options:
            return self._selected
        return options[0] if len(options) == 1 else None

    async def async_select_option(self, option: str) -> None:
        """Pick a store, and put the list in that store's order.

        Re-sorting here rather than waiting to be asked: picking the shop is
        the whole reason this selector exists, and a list still in the previous
        shop's walking route is worse than no order at all.
        """
        self._selected = option
        self._entry.runtime_data.store_choice = option
        self._store.sort_list(ListName.SHOPPING, option)
        self._store.sort_list(ListName.LATER, option)
        self._store.async_schedule_save()
        self.async_write_ha_state()
        # The summary sensor publishes the walking route the cards draw their
        # headings from. Without this it keeps showing the old store's.
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)
