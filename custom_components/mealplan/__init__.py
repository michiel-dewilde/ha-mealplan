# SPDX-License-Identifier: GPL-3.0-or-later
"""The Meal Plan integration.

Owns the domain rather than gluing helpers together: its own to-do lists, its
own calendar, and a body of knowledge that grows as it is used. Everything works
without a language model; the AI layers are additive, and removing them changes
nothing about the rest.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.setup import async_when_setup

from .const import CARDS_DIR, CARDS_FILE, CARDS_URL, DOMAIN
from .http import MealPlanPrintView
from .llm import async_register_api
from .services import async_setup_services
from .store import MealPlanStore
from .types import MealPlanConfigEntry, MealPlanRuntimeData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SELECT, Platform.SENSOR, Platform.TODO]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services and the printable view.

    Both are domain-level: they exist as soon as the integration is loaded, and
    resolve which meal plan they are about when they are called.
    """
    del config
    async_setup_services(hass)
    # Headless setups (and most tests) never start the HTTP component.
    if (http := getattr(hass, "http", None)) is not None:
        http.register_view(MealPlanPrintView())
        await _async_register_cards(hass, http)
    else:
        _LOGGER.debug("HTTP component unavailable; the printable list will not be served")
    return True


async def _async_register_cards(hass: HomeAssistant, http: object) -> None:
    """Serve the dashboard cards and load them into the frontend.

    Registered here rather than left to the user's Lovelace resource list: a
    card that has to be installed by hand is a card that is out of date the
    first time the integration is updated.
    """
    cards = Path(__file__).parent / CARDS_DIR
    if not (cards / CARDS_FILE).exists():
        _LOGGER.debug("No card bundle at %s; the dashboard cards will not be available", cards)
        return
    await http.async_register_static_paths(  # type: ignore[attr-defined]
        [StaticPathConfig(CARDS_URL, str(cards), cache_headers=False)]
    )

    async def _load_cards(hass: HomeAssistant, component: str) -> None:
        """Add the bundle to the frontend once there is a frontend to add it to."""
        del component
        add_extra_js_url(hass, f"{CARDS_URL}/{CARDS_FILE}")

    # Serving the file needs only `http`; loading it needs `frontend`, which
    # may not be up yet — and in a test harness never comes up at all.
    async_when_setup(hass, "frontend", _load_cards)


async def async_setup_entry(hass: HomeAssistant, entry: MealPlanConfigEntry) -> bool:
    """Set up one meal plan."""
    store = MealPlanStore(hass, entry.entry_id)
    await store.async_load()
    entry.runtime_data = MealPlanRuntimeData(store=store)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(async_register_api(hass, entry))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MealPlanConfigEntry) -> bool:
    """Unload one meal plan, writing out anything still pending."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_save_now()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after the options changed."""
    await hass.config_entries.async_reload(entry.entry_id)


__all__ = ["DOMAIN", "async_setup", "async_setup_entry", "async_unload_entry"]
