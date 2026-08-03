# SPDX-License-Identifier: GPL-3.0-or-later
"""Config and options flow."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_CALENDARS,
    CONF_MENU_DAYS,
    CONF_ROLLOVER_DAY,
    CONF_UNDATED_STOCK,
    CONF_WEEK_START,
    DEFAULT_MENU_DAYS,
    DEFAULT_NAME,
    DEFAULT_ROLLOVER_DAY,
    DEFAULT_UNDATED_STOCK,
    DEFAULT_WEEK_START,
    DOMAIN,
    MAX_MENU_DAYS,
    MIN_MENU_DAYS,
    WEEKDAYS,
)


def _weekday_selector() -> selector.SelectSelector:
    """Return a weekday picker whose labels come from the translations."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(WEEKDAYS),
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="weekday",
        )
    )


def _settings_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Return the schema shared by the config and options flow.

    The calendars are an entity selector rather than a hard-coded list: the
    choice survives renames, and no `entity_id` ends up baked into the code.
    """
    return vol.Schema(
        {
            vol.Optional(CONF_CALENDARS, default=defaults.get(CONF_CALENDARS, [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="calendar", multiple=True)
            ),
            vol.Required(CONF_WEEK_START, default=defaults.get(CONF_WEEK_START, DEFAULT_WEEK_START)): (
                _weekday_selector()
            ),
            vol.Required(CONF_MENU_DAYS, default=defaults.get(CONF_MENU_DAYS, DEFAULT_MENU_DAYS)): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_MENU_DAYS, max=MAX_MENU_DAYS, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                )
            ),
            vol.Required(CONF_ROLLOVER_DAY, default=defaults.get(CONF_ROLLOVER_DAY, DEFAULT_ROLLOVER_DAY)): (
                _weekday_selector()
            ),
            vol.Required(
                CONF_UNDATED_STOCK, default=defaults.get(CONF_UNDATED_STOCK, DEFAULT_UNDATED_STOCK)
            ): selector.BooleanSelector(),
        }
    )


class MealPlanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setting up a meal plan."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a name and the planning settings."""
        if user_input is not None:
            name = user_input.pop(CONF_NAME)
            await self.async_set_unique_id(name.casefold())
            self._abort_if_unique_id_configured()
            user_input[CONF_MENU_DAYS] = int(user_input[CONF_MENU_DAYS])
            return self.async_create_entry(title=name, data={CONF_NAME: name}, options=user_input)

        schema = vol.Schema({vol.Required(CONF_NAME, default=DEFAULT_NAME): str}).extend(_settings_schema({}).schema)
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MealPlanOptionsFlow:
        """Return the options flow."""
        return MealPlanOptionsFlow()


class MealPlanOptionsFlow(OptionsFlow):
    """Change the planning settings after setup."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and store the settings."""
        if user_input is not None:
            user_input[CONF_MENU_DAYS] = int(user_input[CONF_MENU_DAYS])
            return self.async_create_entry(data=user_input)

        return self.async_show_form(step_id="init", data_schema=_settings_schema(dict(self.config_entry.options)))
