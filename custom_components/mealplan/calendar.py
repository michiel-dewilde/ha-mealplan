# SPDX-License-Identifier: GPL-3.0-or-later
"""The meal plan as a calendar.

Publication only, and in one direction. The calendars a user selects are read so
the menu screen can show what a day already holds; nothing is ever written back
to them. What this integration plans lives here, in an entity you are free to
ignore.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_UPDATED
from .entity import MealPlanEntity
from .types import MealPlanConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MealPlanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the meal plan calendar."""
    async_add_entities([MealPlanCalendar(entry)])


class MealPlanCalendar(MealPlanEntity, CalendarEntity):
    """One all-day event per planned day."""

    _attr_translation_key = "meal_plan"

    def __init__(self, entry: MealPlanConfigEntry) -> None:
        """Set up the calendar."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_calendar"

    async def async_added_to_hass(self) -> None:
        """Start listening for changes made by the services."""
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        """Redraw after a service changed the plan."""
        self.async_write_ha_state()

    def _event_for(self, day: date) -> CalendarEvent | None:
        """Return the event for a day, or None if nothing is planned.

        An empty day is a normal state — roughly a quarter of them are left open
        on purpose — so it simply has no event rather than an empty one.
        """
        entry = self._store.day(day)
        if not entry.dish:
            return None
        return CalendarEvent(
            start=day,
            end=day + timedelta(days=1),
            summary=entry.dish,
            description=entry.note,
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return today's meal, or the next one that is planned."""
        today = self._today
        planned = sorted(day for day, entry in self._store.data.plan.items() if entry.dish and day >= today)
        return self._event_for(planned[0]) if planned else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the planned meals in a window."""
        start = start_date.date()
        end = end_date.date()
        events = [self._event_for(day) for day in sorted(self._store.data.plan) if start <= day <= end]
        return [event for event in events if event is not None]
