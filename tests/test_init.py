"""Setting up, unloading, and what the entities look like."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import DOMAIN


async def test_setup_creates_every_entity(hass: HomeAssistant, entry: MockConfigEntry):
    """Three lists, a calendar, a store selector and a summary."""
    assert entry.state is ConfigEntryState.LOADED

    states = {state.entity_id for state in hass.states.async_all()}
    assert "todo.meal_plan_shopping_list" in states
    assert "todo.meal_plan_next_trip" in states
    assert "todo.meal_plan_in_the_house" in states
    assert "calendar.meal_plan_meal_plan" in states
    assert "select.meal_plan_store" in states
    assert "sensor.meal_plan_summary" in states


async def test_every_service_is_registered(hass: HomeAssistant, entry: MockConfigEntry):
    """Reading services matter as much as writing ones."""
    services = hass.services.async_services_for_domain(DOMAIN)
    for name in ("add_dish", "running_low", "plan_menu", "complete_all", "sort_list", "set_expiry"):
        assert name in services, f"missing writing service {name}"
    for name in ("get_week", "list_dishes", "get_pantry_check", "get_expiring", "suggest_menu"):
        assert name in services, f"missing reading service {name}"
        assert services[name].supports_response is not None


async def test_unload(hass: HomeAssistant, entry: MockConfigEntry):
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
