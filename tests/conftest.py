"""Shared fixtures."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import (
    CONF_CALENDARS,
    CONF_MENU_DAYS,
    CONF_ROLLOVER_DAY,
    CONF_UNDATED_STOCK,
    CONF_WEEK_START,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant find `custom_components/mealplan`."""
    return


@pytest.fixture
def options() -> dict[str, Any]:
    """Return the default planning options."""
    return {
        CONF_CALENDARS: [],
        CONF_WEEK_START: "sat",
        CONF_MENU_DAYS: 7,
        CONF_ROLLOVER_DAY: "thu",
        CONF_UNDATED_STOCK: True,
    }


@pytest.fixture
async def entry(hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
    """Set up a meal plan with an empty knowledge base."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Meal plan",
        data={CONF_NAME: "Meal plan"},
        options=options,
        unique_id="meal plan",
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def knowledge() -> dict[str, Any]:
    """Return a small but complete schema 2.0 knowledge file.

    Invented content behind real field names. The names are a contract and are
    English; what a household actually seeds is its own business and never
    belongs in a repository other people read.

    Two dishes, a fresh and a pantry article each, a store with a walking route,
    and an article that is only sold in one shop.
    """
    return {
        "schema": "2.1",
        "generated": "2026-08-03",
        "source": {"weekly_plans": 40, "holdout_weeks": [], "recipe_list": 40},
        "departments": [
            {
                "key": "produce",
                "kind": "fresh",
                "shelf_life": "ignore",
                "labels": {"en": "Produce", "nl": "Groenten & fruit"},
            },
            {
                "key": "butcher",
                "kind": "fresh",
                "shelf_life": "important",
                "labels": {"en": "Butcher", "nl": "Beenhouwerij"},
            },
            {
                "key": "dry_goods",
                "kind": "pantry",
                "shelf_life": "ignore",
                "labels": {"en": "Dry goods", "nl": "Droge voeding"},
            },
        ],
        "stores": {
            "Corner Market": {
                "department_order": ["produce", "butcher", "dry_goods"],
                "lists": 36,
                "source": "derived",
            }
        },
        "articles": [
            {
                "name": "minced beef",
                "department": "butcher",
                "kind": "fresh",
                "department_source": "table",
                "times": 13,
                "last_listed": "2026-07-30",
                "cadence_days": 21.0,
                "staple": False,
                "frozen": False,
                "availability": None,
                "shelf_life": "important",
                "expiry_seen": True,
            },
            {
                "name": "tomatoes",
                "department": "produce",
                "kind": "fresh",
                "department_source": "table",
                "times": 9,
                "last_listed": "2026-07-25",
                "cadence_days": 30.0,
                "staple": True,
                "frozen": False,
                "availability": None,
                "shelf_life": "ignore",
                "expiry_seen": False,
            },
            {
                "name": "rice",
                "department": "dry_goods",
                "kind": "pantry",
                "department_source": "table",
                "times": 6,
                "last_listed": "2026-06-01",
                "cadence_days": 35.0,
                "staple": True,
                "frozen": False,
                "availability": None,
                "shelf_life": "ignore",
                "expiry_seen": False,
            },
            {
                "name": "poultry rub",
                "department": "dry_goods",
                "kind": "pantry",
                "department_source": "rule",
                "times": 2,
                "last_listed": None,
                "cadence_days": None,
                "staple": False,
                "frozen": False,
                "availability": "Big Barn",
                "shelf_life": "ignore",
                "expiry_seen": False,
            },
        ],
        "dishes": [
            {
                "name": "tacos",
                "times": 18,
                "last": "2026-07-24",
                "usual_day": "fri",
                "interval_days": 10.0,
                "veggie_variants": 2,
                "recipe_list": "tacos",
                "ingredients": [
                    {
                        "article": "minced beef",
                        "certainty": "certain",
                        "source": "recipe_list",
                        "department": "butcher",
                    },
                    {"article": "tomatoes", "certainty": "likely", "source": "co_occurrence", "department": "produce"},
                    {
                        "article": "poultry rub",
                        "certainty": "certain",
                        "source": "recipe_list",
                        "department": "dry_goods",
                    },
                ],
            },
            {
                "name": "rice",
                "times": 11,
                "last": "2026-07-21",
                "usual_day": "tue",
                "interval_days": 14.0,
                "veggie_variants": 0,
                "recipe_list": None,
                "ingredients": [
                    {"article": "rice", "certainty": "certain", "source": "recipe_list", "department": "dry_goods"},
                ],
            },
        ],
        "recipe_list_unused": ["carrot gratin"],
        "calendar": {"annotations": 218, "day_with_event": 190, "semantic_match": 159},
    }


@pytest.fixture
def today() -> date:
    """Return a fixed Thursday, the evening the menu gets filled in."""
    return date(2026, 8, 6)
