# SPDX-License-Identifier: GPL-3.0-or-later
"""Service registration.

A thin layer: validate, resolve which meal plan is meant, hand off to `api`.
Everything these services do, the LLM tools do too, through the same functions.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from . import api
from .const import (
    ATTR_ARTICLE,
    ATTR_ARTICLES,
    ATTR_DATE,
    ATTR_DAYS,
    ATTR_DEPARTMENTS,
    ATTR_DISH,
    ATTR_ENOUGH,
    ATTR_ENTRY_ID,
    ATTR_EXCEPT_ITEMS,
    ATTR_EXPIRY,
    ATTR_FROM,
    ATTR_INCLUDE_COMPLETED,
    ATTR_INCLUDE_PANTRY,
    ATTR_INGREDIENTS,
    ATTR_INTO,
    ATTR_ITEM,
    ATTR_KIND,
    ATTR_KNOWLEDGE,
    ATTR_LABELS,
    ATTR_LIMIT,
    ATTR_LIST,
    ATTR_MOVE_TO,
    ATTR_NAME,
    ATTR_NOTE,
    ATTR_OFFSET,
    ATTR_PEOPLE,
    ATTR_POSITION,
    ATTR_ROUND,
    ATTR_SCOPE,
    ATTR_SEARCH,
    ATTR_SERVINGS,
    ATTR_SINCE,
    ATTR_START,
    ATTR_STORE,
    ATTR_TO,
    ATTR_UNTIL,
    ATTR_WHEN,
    DOMAIN,
    SERVICE_ADD_DISH,
    SERVICE_CHECK_OFF,
    SERVICE_COMPLETE_ALL,
    SERVICE_DISCARD_DELETED,
    SERVICE_EXPORT_KNOWLEDGE,
    SERVICE_FORGET_EVENTS,
    SERVICE_GET_DELETED,
    SERVICE_GET_EXPIRING,
    SERVICE_GET_HISTORY,
    SERVICE_GET_LIST,
    SERVICE_GET_PANTRY_CHECK,
    SERVICE_GET_WEEK,
    SERVICE_IMPORT_KNOWLEDGE,
    SERVICE_LEARN_DISH,
    SERVICE_LIST_ARTICLES,
    SERVICE_LIST_DEPARTMENTS,
    SERVICE_LIST_DISHES,
    SERVICE_MERGE_ARTICLES,
    SERVICE_MOVE_ALL,
    SERVICE_MOVE_ITEM,
    SERVICE_PLAN_MENU,
    SERVICE_PRINT_LIST,
    SERVICE_REMOVE_ARTICLE,
    SERVICE_REMOVE_DEPARTMENT,
    SERVICE_REMOVE_DISH,
    SERVICE_REMOVE_STORE,
    SERVICE_RENAME_ARTICLE,
    SERVICE_RESET_ROUND,
    SERVICE_RESTORE_DELETED,
    SERVICE_RUNNING_LOW,
    SERVICE_SET_DEPARTMENT,
    SERVICE_SET_DISH,
    SERVICE_SET_EXPIRY,
    SERVICE_SET_STORE,
    SERVICE_SET_STORE_ORDER,
    SERVICE_SORT_LIST,
    SERVICE_SUGGEST_MENU,
    UNKNOWN_DEPARTMENT,
    WEEKDAYS,
    EventKind,
    Kind,
    ListName,
    PantryScope,
    Round,
    ShelfLife,
    When,
)
from .knowledge import export_knowledge, import_knowledge
from .types import MealPlanConfigEntry

SERVICE_ADD_STOCK = "add_stock"
SERVICE_LEARN_ARTICLE = "learn_article"
SERVICE_SET_WINDOW = "set_window"

ATTR_CLEAR = "clear"
ATTR_DEPARTMENT = "department"
ATTR_END = "end"
ATTR_EXTEND_DAYS = "extend_days"
ATTR_RECIPE_LIST = "recipe_list"
ATTR_REPLACE = "replace"
ATTR_RESET = "reset"
ATTR_SHELF_LIFE = "shelf_life"
ATTR_STAPLE = "staple"
ATTR_USUAL_DAY = "usual_day"
ATTR_AVAILABILITY = "availability"

_ENTRY = {vol.Optional(ATTR_ENTRY_ID): cv.string}


def _schema(fields: dict[Any, Any]) -> vol.Schema:
    """Build a service schema with the optional entry selector included."""
    return vol.Schema({**_ENTRY, **fields})


@callback
def _resolve(hass: HomeAssistant, call: ServiceCall) -> MealPlanConfigEntry:
    """Find which meal plan a call is about.

    With a single meal plan configured — which is the normal case — the field
    can be left out entirely.
    """
    entries: list[MealPlanConfigEntry] = [
        entry for entry in hass.config_entries.async_loaded_entries(DOMAIN) if hasattr(entry, "runtime_data")
    ]
    if entry_id := call.data.get(ATTR_ENTRY_ID):
        match = next((entry for entry in entries if entry.entry_id == entry_id), None)
        if match is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_entry",
                translation_placeholders={"entry_id": entry_id},
            )
        return match
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_meal_plan")
    if len(entries) > 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="ambiguous_meal_plan")
    return entries[0]


def _ctx(hass: HomeAssistant, call: ServiceCall) -> api.Context:
    """Build an api context for a service call."""
    return api.context(hass, _resolve(hass, call))


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register every service the integration offers."""
    register = hass.services.async_register

    # ------------------------------------------------------------ writing

    async def handle_add_dish(call: ServiceCall) -> ServiceResponse:
        return api.add_dish(
            _ctx(hass, call),
            call.data[ATTR_DISH],
            servings=call.data.get(ATTR_SERVINGS),
            include_pantry=call.data.get(ATTR_INCLUDE_PANTRY, False),
        )

    register(
        DOMAIN,
        SERVICE_ADD_DISH,
        handle_add_dish,
        schema=_schema(
            {
                vol.Required(ATTR_DISH): cv.string,
                vol.Optional(ATTR_SERVINGS): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
                vol.Optional(ATTR_INCLUDE_PANTRY): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_running_low(call: ServiceCall) -> ServiceResponse:
        return api.running_low(_ctx(hass, call), call.data[ATTR_ARTICLE], When(call.data.get(ATTR_WHEN, When.NOW)))

    register(
        DOMAIN,
        SERVICE_RUNNING_LOW,
        handle_running_low,
        schema=_schema(
            {
                vol.Required(ATTR_ARTICLE): cv.string,
                vol.Optional(ATTR_WHEN, default=str(When.NOW)): vol.In([str(w) for w in When]),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_plan_menu(call: ServiceCall) -> ServiceResponse:
        return api.plan_menu(
            _ctx(hass, call),
            call.data[ATTR_DATE],
            dish=call.data.get(ATTR_DISH),
            note=call.data.get(ATTR_NOTE),
            people=call.data.get(ATTR_PEOPLE),
            clear=call.data.get(ATTR_CLEAR, False),
        )

    register(
        DOMAIN,
        SERVICE_PLAN_MENU,
        handle_plan_menu,
        schema=_schema(
            {
                vol.Required(ATTR_DATE): cv.date,
                vol.Optional(ATTR_DISH): cv.string,
                vol.Optional(ATTR_NOTE): cv.string,
                vol.Optional(ATTR_PEOPLE): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
                vol.Optional(ATTR_CLEAR): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_complete_all(call: ServiceCall) -> ServiceResponse:
        return api.complete_all(_ctx(hass, call), call.data.get(ATTR_EXCEPT_ITEMS))

    register(
        DOMAIN,
        SERVICE_COMPLETE_ALL,
        handle_complete_all,
        schema=_schema({vol.Optional(ATTR_EXCEPT_ITEMS): vol.All(cv.ensure_list, [cv.string])}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_sort_list(call: ServiceCall) -> ServiceResponse:
        return api.sort_list(_ctx(hass, call), call.data.get(ATTR_STORE))

    register(
        DOMAIN,
        SERVICE_SORT_LIST,
        handle_sort_list,
        schema=_schema({vol.Optional(ATTR_STORE): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_set_store_order(call: ServiceCall) -> ServiceResponse:
        return api.set_store_order(_ctx(hass, call), call.data[ATTR_DEPARTMENTS], call.data.get(ATTR_STORE))

    register(
        DOMAIN,
        SERVICE_SET_STORE_ORDER,
        handle_set_store_order,
        schema=_schema(
            {
                vol.Required(ATTR_DEPARTMENTS): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(ATTR_STORE): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_check_off(call: ServiceCall) -> ServiceResponse:
        return api.check_off(
            _ctx(hass, call),
            articles=call.data.get(ATTR_ARTICLES),
            enough=call.data.get(ATTR_ENOUGH, True),
            round_name=Round(call.data.get(ATTR_ROUND, Round.PANTRY)),
            scope=PantryScope(call.data.get(ATTR_SCOPE, PantryScope.GENERAL)),
            when=When(call.data.get(ATTR_WHEN, When.NOW)),
        )

    register(
        DOMAIN,
        SERVICE_CHECK_OFF,
        handle_check_off,
        schema=_schema(
            {
                vol.Optional(ATTR_ARTICLES): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(ATTR_ENOUGH, default=True): cv.boolean,
                vol.Optional(ATTR_ROUND, default=str(Round.PANTRY)): vol.In([str(r) for r in Round]),
                vol.Optional(ATTR_SCOPE, default=str(PantryScope.GENERAL)): vol.In([str(s) for s in PantryScope]),
                vol.Optional(ATTR_WHEN, default=str(When.NOW)): vol.In([str(w) for w in When]),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_reset_round(call: ServiceCall) -> ServiceResponse:
        return api.reset_round(_ctx(hass, call), Round(call.data.get(ATTR_ROUND, Round.PANTRY)))

    register(
        DOMAIN,
        SERVICE_RESET_ROUND,
        handle_reset_round,
        schema=_schema({vol.Optional(ATTR_ROUND, default=str(Round.PANTRY)): vol.In([str(r) for r in Round])}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_move_item(call: ServiceCall) -> ServiceResponse:
        return api.move_item(_ctx(hass, call), call.data[ATTR_ITEM], ListName(call.data[ATTR_TO]))

    register(
        DOMAIN,
        SERVICE_MOVE_ITEM,
        handle_move_item,
        schema=_schema(
            {
                vol.Required(ATTR_ITEM): cv.string,
                vol.Required(ATTR_TO): vol.In([str(name) for name in ListName]),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_move_all(call: ServiceCall) -> ServiceResponse:
        return api.move_all(
            _ctx(hass, call),
            ListName(call.data[ATTR_TO]),
            ListName(call.data.get(ATTR_FROM, ListName.LATER)),
        )

    register(
        DOMAIN,
        SERVICE_MOVE_ALL,
        handle_move_all,
        schema=_schema(
            {
                vol.Required(ATTR_TO): vol.In([str(name) for name in ListName]),
                vol.Optional(ATTR_FROM, default=str(ListName.LATER)): vol.In([str(name) for name in ListName]),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_set_expiry(call: ServiceCall) -> ServiceResponse:
        return api.set_expiry(_ctx(hass, call), call.data[ATTR_ARTICLE], call.data[ATTR_EXPIRY])

    register(
        DOMAIN,
        SERVICE_SET_EXPIRY,
        handle_set_expiry,
        schema=_schema({vol.Required(ATTR_ARTICLE): cv.string, vol.Required(ATTR_EXPIRY): cv.date}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_add_stock(call: ServiceCall) -> ServiceResponse:
        return api.add_stock(_ctx(hass, call), call.data[ATTR_ARTICLE], call.data.get(ATTR_EXPIRY))

    register(
        DOMAIN,
        SERVICE_ADD_STOCK,
        handle_add_stock,
        schema=_schema({vol.Required(ATTR_ARTICLE): cv.string, vol.Optional(ATTR_EXPIRY): cv.date}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_learn_dish(call: ServiceCall) -> ServiceResponse:
        return api.learn_dish(
            _ctx(hass, call),
            call.data[ATTR_DISH],
            call.data.get(ATTR_INGREDIENTS, []),
            usual_day=call.data.get(ATTR_USUAL_DAY),
            recipe_list=call.data.get(ATTR_RECIPE_LIST),
        )

    register(
        DOMAIN,
        SERVICE_LEARN_DISH,
        handle_learn_dish,
        schema=_schema(
            {
                vol.Required(ATTR_DISH): cv.string,
                vol.Optional(ATTR_INGREDIENTS): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(ATTR_USUAL_DAY): vol.In(list(WEEKDAYS)),
                vol.Optional(ATTR_RECIPE_LIST): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_learn_article(call: ServiceCall) -> ServiceResponse:
        shelf_life = call.data.get(ATTR_SHELF_LIFE)
        return api.learn_article(
            _ctx(hass, call),
            call.data[ATTR_ARTICLE],
            call.data[ATTR_DEPARTMENT],
            shelf_life=ShelfLife(shelf_life) if shelf_life else None,
            staple=call.data.get(ATTR_STAPLE),
            availability=call.data.get(ATTR_AVAILABILITY),
        )

    register(
        DOMAIN,
        SERVICE_LEARN_ARTICLE,
        handle_learn_article,
        schema=_schema(
            {
                vol.Required(ATTR_ARTICLE): cv.string,
                vol.Required(ATTR_DEPARTMENT): cv.string,
                vol.Optional(ATTR_SHELF_LIFE): vol.In([str(s) for s in ShelfLife]),
                vol.Optional(ATTR_STAPLE): cv.boolean,
                vol.Optional(ATTR_AVAILABILITY): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    # ------------------------------------------------------------ management

    async def handle_set_dish(call: ServiceCall) -> ServiceResponse:
        return api.set_dish(
            _ctx(hass, call),
            call.data[ATTR_DISH],
            ingredients=call.data.get(ATTR_INGREDIENTS),
            usual_day=call.data.get(ATTR_USUAL_DAY),
            recipe_list=call.data.get(ATTR_RECIPE_LIST),
        )

    register(
        DOMAIN,
        SERVICE_SET_DISH,
        handle_set_dish,
        schema=_schema(
            {
                vol.Required(ATTR_DISH): cv.string,
                vol.Optional(ATTR_INGREDIENTS): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(ATTR_USUAL_DAY): vol.Any("", vol.In(list(WEEKDAYS))),
                vol.Optional(ATTR_RECIPE_LIST): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_remove_dish(call: ServiceCall) -> ServiceResponse:
        return api.remove_dish(_ctx(hass, call), call.data[ATTR_DISH])

    register(
        DOMAIN,
        SERVICE_REMOVE_DISH,
        handle_remove_dish,
        schema=_schema({vol.Required(ATTR_DISH): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_remove_article(call: ServiceCall) -> ServiceResponse:
        return api.remove_article(_ctx(hass, call), call.data[ATTR_ARTICLE])

    register(
        DOMAIN,
        SERVICE_REMOVE_ARTICLE,
        handle_remove_article,
        schema=_schema({vol.Required(ATTR_ARTICLE): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_rename_article(call: ServiceCall) -> ServiceResponse:
        return api.rename_article(_ctx(hass, call), call.data[ATTR_ARTICLE], call.data[ATTR_TO])

    register(
        DOMAIN,
        SERVICE_RENAME_ARTICLE,
        handle_rename_article,
        schema=_schema({vol.Required(ATTR_ARTICLE): cv.string, vol.Required(ATTR_TO): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_merge_articles(call: ServiceCall) -> ServiceResponse:
        return api.merge_articles(_ctx(hass, call), call.data[ATTR_ARTICLE], call.data[ATTR_INTO])

    register(
        DOMAIN,
        SERVICE_MERGE_ARTICLES,
        handle_merge_articles,
        schema=_schema({vol.Required(ATTR_ARTICLE): cv.string, vol.Required(ATTR_INTO): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_set_department(call: ServiceCall) -> ServiceResponse:
        kind = call.data.get(ATTR_KIND)
        shelf_life = call.data.get(ATTR_SHELF_LIFE)
        return api.set_department(
            _ctx(hass, call),
            call.data[ATTR_DEPARTMENT],
            labels=call.data.get(ATTR_LABELS),
            kind=Kind(kind) if kind else None,
            shelf_life=ShelfLife(shelf_life) if shelf_life else None,
            position=call.data.get(ATTR_POSITION),
        )

    register(
        DOMAIN,
        SERVICE_SET_DEPARTMENT,
        handle_set_department,
        schema=_schema(
            {
                vol.Required(ATTR_DEPARTMENT): cv.string,
                vol.Optional(ATTR_LABELS): dict,
                vol.Optional(ATTR_KIND): vol.In([str(k) for k in Kind]),
                vol.Optional(ATTR_SHELF_LIFE): vol.In([str(s) for s in ShelfLife]),
                vol.Optional(ATTR_POSITION): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_remove_department(call: ServiceCall) -> ServiceResponse:
        return api.remove_department(
            _ctx(hass, call), call.data[ATTR_DEPARTMENT], call.data.get(ATTR_MOVE_TO, UNKNOWN_DEPARTMENT)
        )

    register(
        DOMAIN,
        SERVICE_REMOVE_DEPARTMENT,
        handle_remove_department,
        schema=_schema(
            {
                vol.Required(ATTR_DEPARTMENT): cv.string,
                vol.Optional(ATTR_MOVE_TO, default=UNKNOWN_DEPARTMENT): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_set_store(call: ServiceCall) -> ServiceResponse:
        return api.set_store(_ctx(hass, call), call.data[ATTR_NAME])

    register(
        DOMAIN,
        SERVICE_SET_STORE,
        handle_set_store,
        schema=_schema({vol.Required(ATTR_NAME): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_remove_store(call: ServiceCall) -> ServiceResponse:
        return api.remove_store(_ctx(hass, call), call.data[ATTR_NAME])

    register(
        DOMAIN,
        SERVICE_REMOVE_STORE,
        handle_remove_store,
        schema=_schema({vol.Required(ATTR_NAME): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_restore_deleted(call: ServiceCall) -> ServiceResponse:
        return api.restore_deleted(_ctx(hass, call), call.data[ATTR_NAME], call.data.get(ATTR_KIND, "article"))

    register(
        DOMAIN,
        SERVICE_RESTORE_DELETED,
        handle_restore_deleted,
        schema=_schema(
            {
                vol.Required(ATTR_NAME): cv.string,
                vol.Optional(ATTR_KIND, default="article"): vol.In(["article", "dish"]),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_discard_deleted(call: ServiceCall) -> ServiceResponse:
        return api.discard_deleted(_ctx(hass, call), call.data[ATTR_NAME], call.data.get(ATTR_KIND, "article"))

    register(
        DOMAIN,
        SERVICE_DISCARD_DELETED,
        handle_discard_deleted,
        schema=_schema(
            {
                vol.Required(ATTR_NAME): cv.string,
                vol.Optional(ATTR_KIND, default="article"): vol.In(["article", "dish"]),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_forget_events(call: ServiceCall) -> ServiceResponse:
        kind = call.data.get(ATTR_KIND)
        return api.forget_events(
            _ctx(hass, call),
            call.data[ATTR_SINCE],
            call.data[ATTR_UNTIL],
            EventKind(kind) if kind else None,
        )

    register(
        DOMAIN,
        SERVICE_FORGET_EVENTS,
        handle_forget_events,
        schema=_schema(
            {
                vol.Required(ATTR_SINCE): cv.date,
                vol.Required(ATTR_UNTIL): cv.date,
                vol.Optional(ATTR_KIND): vol.In([str(kind) for kind in EventKind]),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_set_window(call: ServiceCall) -> ServiceResponse:
        return api.set_window(
            _ctx(hass, call),
            end=call.data.get(ATTR_END),
            extend_days=call.data.get(ATTR_EXTEND_DAYS),
            reset=call.data.get(ATTR_RESET, False),
        )

    register(
        DOMAIN,
        SERVICE_SET_WINDOW,
        handle_set_window,
        schema=_schema(
            {
                vol.Optional(ATTR_END): cv.date,
                vol.Optional(ATTR_EXTEND_DAYS): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                vol.Optional(ATTR_RESET): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_print_list(call: ServiceCall) -> ServiceResponse:
        from .http import PRINT_URL, render_list  # noqa: PLC0415 - avoids importing aiohttp at module load

        entry = _resolve(hass, call)
        return {"url": f"{PRINT_URL}/{entry.entry_id}", "html": render_list(hass, entry)}

    register(
        DOMAIN,
        SERVICE_PRINT_LIST,
        handle_print_list,
        schema=_schema({}),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_import(call: ServiceCall) -> ServiceResponse:
        ctx = _ctx(hass, call)
        result = import_knowledge(ctx.store, call.data[ATTR_KNOWLEDGE], replace=call.data.get(ATTR_REPLACE, False))
        ctx.commit()
        return result

    register(
        DOMAIN,
        SERVICE_IMPORT_KNOWLEDGE,
        handle_import,
        schema=_schema({vol.Required(ATTR_KNOWLEDGE): dict, vol.Optional(ATTR_REPLACE): cv.boolean}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_export(call: ServiceCall) -> ServiceResponse:
        ctx = _ctx(hass, call)
        return export_knowledge(ctx.store, ctx.today)

    register(
        DOMAIN,
        SERVICE_EXPORT_KNOWLEDGE,
        handle_export,
        schema=_schema({}),
        supports_response=SupportsResponse.ONLY,
    )

    # ------------------------------------------------------------ reading

    async def handle_get_week(call: ServiceCall) -> ServiceResponse:
        return await api.get_week(_ctx(hass, call), call.data.get(ATTR_START))

    register(
        DOMAIN,
        SERVICE_GET_WEEK,
        handle_get_week,
        schema=_schema({vol.Optional(ATTR_START): cv.date}),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_get_history(call: ServiceCall) -> ServiceResponse:
        kind = call.data.get(ATTR_KIND)
        return api.get_history(
            _ctx(hass, call),
            since=call.data.get(ATTR_SINCE),
            until=call.data.get(ATTR_UNTIL),
            article=call.data.get(ATTR_ARTICLE),
            dish=call.data.get(ATTR_DISH),
            kind=EventKind(kind) if kind else None,
            limit=call.data.get(ATTR_LIMIT, api.DEFAULT_HISTORY_LIMIT),
            offset=call.data.get(ATTR_OFFSET, 0),
        )

    register(
        DOMAIN,
        SERVICE_GET_HISTORY,
        handle_get_history,
        schema=_schema(
            {
                vol.Optional(ATTR_SINCE): cv.date,
                vol.Optional(ATTR_UNTIL): cv.date,
                vol.Optional(ATTR_ARTICLE): cv.string,
                vol.Optional(ATTR_DISH): cv.string,
                vol.Optional(ATTR_KIND): vol.In([str(kind) for kind in EventKind]),
                vol.Optional(ATTR_LIMIT): vol.All(vol.Coerce(int), vol.Range(min=1, max=api.MAX_HISTORY_LIMIT)),
                vol.Optional(ATTR_OFFSET): vol.All(vol.Coerce(int), vol.Range(min=0)),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_get_list(call: ServiceCall) -> ServiceResponse:
        return api.get_list(
            _ctx(hass, call),
            ListName(call.data.get(ATTR_LIST, ListName.SHOPPING)),
            include_completed=call.data.get(ATTR_INCLUDE_COMPLETED, False),
        )

    register(
        DOMAIN,
        SERVICE_GET_LIST,
        handle_get_list,
        schema=_schema(
            {
                vol.Optional(ATTR_LIST, default=str(ListName.SHOPPING)): vol.In([str(name) for name in ListName]),
                vol.Optional(ATTR_INCLUDE_COMPLETED): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_list_dishes(call: ServiceCall) -> ServiceResponse:
        return api.list_dishes(_ctx(hass, call))

    register(
        DOMAIN,
        SERVICE_LIST_DISHES,
        handle_list_dishes,
        schema=_schema({}),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_list_articles(call: ServiceCall) -> ServiceResponse:
        return api.list_articles(_ctx(hass, call), call.data.get(ATTR_SEARCH))

    register(
        DOMAIN,
        SERVICE_LIST_ARTICLES,
        handle_list_articles,
        schema=_schema({vol.Optional(ATTR_SEARCH): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_list_departments(call: ServiceCall) -> ServiceResponse:
        return api.list_departments(_ctx(hass, call))

    register(
        DOMAIN,
        SERVICE_LIST_DEPARTMENTS,
        handle_list_departments,
        schema=_schema({}),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_get_deleted(call: ServiceCall) -> ServiceResponse:
        return api.get_deleted(_ctx(hass, call))

    register(
        DOMAIN,
        SERVICE_GET_DELETED,
        handle_get_deleted,
        schema=_schema({}),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_pantry_check(call: ServiceCall) -> ServiceResponse:
        return api.get_pantry_check(_ctx(hass, call), PantryScope(call.data.get(ATTR_SCOPE, PantryScope.GENERAL)))

    register(
        DOMAIN,
        SERVICE_GET_PANTRY_CHECK,
        handle_pantry_check,
        schema=_schema(
            {vol.Optional(ATTR_SCOPE, default=str(PantryScope.GENERAL)): vol.In([str(s) for s in PantryScope])}
        ),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_get_expiring(call: ServiceCall) -> ServiceResponse:
        return api.get_expiring(_ctx(hass, call), call.data.get(ATTR_DAYS, api.DEFAULT_EXPIRY_HORIZON_DAYS))

    register(
        DOMAIN,
        SERVICE_GET_EXPIRING,
        handle_get_expiring,
        schema=_schema({vol.Optional(ATTR_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365))}),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_suggest_menu(call: ServiceCall) -> ServiceResponse:
        return api.suggest_menu(
            _ctx(hass, call),
            start=call.data.get(ATTR_START),
            days=call.data.get(ATTR_DAYS),
            limit=call.data.get(ATTR_LIMIT, api.DEFAULT_SUGGESTION_LIMIT),
        )

    register(
        DOMAIN,
        SERVICE_SUGGEST_MENU,
        handle_suggest_menu,
        schema=_schema(
            {
                vol.Optional(ATTR_START): cv.date,
                vol.Optional(ATTR_DAYS): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
                vol.Optional(ATTR_LIMIT): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
