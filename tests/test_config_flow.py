"""The config and options flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import (
    CONF_CALENDARS,
    CONF_MENU_DAYS,
    CONF_ROLLOVER_DAY,
    CONF_UNDATED_STOCK,
    CONF_WEEK_START,
    DOMAIN,
)


async def test_user_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Weekly plan",
            CONF_CALENDARS: [],
            CONF_WEEK_START: "sat",
            CONF_MENU_DAYS: 7,
            CONF_ROLLOVER_DAY: "thu",
            CONF_UNDATED_STOCK: True,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Weekly plan"
    assert result["data"] == {CONF_NAME: "Weekly plan"}
    assert result["options"][CONF_MENU_DAYS] == 7


async def test_the_same_name_twice_is_refused(hass: HomeAssistant, entry: MockConfigEntry):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Meal plan",
            CONF_CALENDARS: [],
            CONF_WEEK_START: "sat",
            CONF_MENU_DAYS: 7,
            CONF_ROLLOVER_DAY: "thu",
            CONF_UNDATED_STOCK: True,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_changes_the_cycle(hass: HomeAssistant, entry: MockConfigEntry):
    """The cycle has changed once already in this household; it will again."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CALENDARS: ["calendar.family"],
            CONF_WEEK_START: "fri",
            CONF_MENU_DAYS: 11,
            CONF_ROLLOVER_DAY: "wed",
            CONF_UNDATED_STOCK: False,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_WEEK_START] == "fri"
    assert entry.options[CONF_MENU_DAYS] == 11
    assert entry.options[CONF_CALENDARS] == ["calendar.family"]
