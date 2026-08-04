# SPDX-License-Identifier: GPL-3.0-or-later
"""The summary sensor.

State is the number of things still to buy. The attributes are what the
dashboard cards read: the window, the menu in it, what is about to expire, and
the departments in walking order.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_UPDATED, URGENT_EXPIRY_DAYS, ListName, ShelfLife
from .entity import MealPlanEntity
from .options import plan_options
from .types import MealPlanConfigEntry
from .window import menu_window, weekday_key


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MealPlanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the summary sensor."""
    async_add_entities([MealPlanSensor(entry)])


class MealPlanSensor(MealPlanEntity, SensorEntity):
    """How much is still open, plus everything the cards need."""

    _attr_translation_key = "summary"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "items"

    def __init__(self, entry: MealPlanConfigEntry) -> None:
        """Set up the sensor."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_summary"

    async def async_added_to_hass(self) -> None:
        """Start listening for changes."""
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        """Redraw after anything changed."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return how many items are still to buy."""
        return len(self._store.open_items(ListName.SHOPPING))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return everything the dashboard cards read."""
        store = self._store
        today = self._today
        options = plan_options(self._entry)
        language = self.hass.config.language
        chosen_store = self._entry.runtime_data.store_choice

        window = menu_window(
            today,
            options.week_start,
            options.menu_days,
            options.rollover_day,
            store.data.window_end,
        )

        expiring = sorted(
            (item for item in store.open_items(ListName.STOCK) if item.due is not None),
            key=lambda item: item.due,  # type: ignore[arg-type, return-value]
        )
        next_expiry = expiring[0].due if expiring else None

        return {
            "entry_id": self._entry.entry_id,
            "entities": self._entity_ids(),
            "store": chosen_store,
            "window_start": window.start.isoformat(),
            "window_end": window.end.isoformat(),
            "window_extended": window.extended,
            "menu": [
                {
                    "date": day.isoformat(),
                    "weekday": weekday_key(day),
                    "dish": store.day(day).dish,
                    "note": store.day(day).note,
                    "people": store.day(day).people,
                }
                for day in window.days
            ],
            "today_dish": store.day(today).dish,
            "tomorrow_dish": store.day(today + timedelta(days=1)).dish,
            "open_items": len(store.open_items(ListName.SHOPPING)),
            "later_items": len(store.open_items(ListName.LATER)),
            "stock_items": len(store.open_items(ListName.STOCK)),
            "next_expiry": next_expiry.isoformat() if next_expiry else None,
            "expiry_urgent": bool(next_expiry and (next_expiry - today).days <= URGENT_EXPIRY_DAYS),
            "expiring": [
                {"summary": item.summary, "due": item.due.isoformat()}  # type: ignore[union-attr]
                for item in expiring
                if (item.due - today).days <= URGENT_EXPIRY_DAYS * 3  # type: ignore[operator]
            ],
            "departments": [
                {
                    "key": key,
                    "label": store.department_label(key, language),
                    "kind": getattr(store.department(key), "kind", None),
                }
                for key in store.store_order(chosen_store)
            ],
            "staples": sorted(
                article.name
                for article in store.data.articles.values()
                if article.staple and store.article_kind(article.name) is not None
            ),
            "watch_expiry": sorted(
                article.name for article in store.data.articles.values() if article.shelf_life == ShelfLife.IMPORTANT
            ),
            "learn_suggestions": store.learn_suggestions(),
            "dishes": sorted(store.data.dishes),
        }

    def _entity_ids(self) -> dict[str, str]:
        """Return this meal plan's other entities, keyed by role.

        The cards need to tick an item off a to-do list, and entity ids are
        localised — `todo.weekplanning_boodschappen` here, `todo.meal_plan_shopping`
        on an English install. Guessing the name is how a card breaks in someone
        else's house; the registry knows.
        """
        registry = er.async_get(self.hass)
        prefix = f"{self._entry.entry_id}_"
        return {
            entry.unique_id.removeprefix(prefix): entry.entity_id
            for entry in er.async_entries_for_config_entry(registry, self._entry.entry_id)
            if entry.unique_id.startswith(prefix)
        }
