# SPDX-License-Identifier: GPL-3.0-or-later
"""Constants for the Meal Plan integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "mealplan"

# Storage
STORAGE_KEY: Final = f"{DOMAIN}.data"
STORAGE_VERSION: Final = 1

# The knowledge file schema this integration reads and writes.
KNOWLEDGE_SCHEMA: Final = "2.3"

# Configuration
CONF_CALENDARS: Final = "calendars"
CONF_WEEK_START: Final = "week_start"
CONF_MENU_DAYS: Final = "menu_days"
CONF_ROLLOVER_DAY: Final = "rollover_day"
CONF_UNDATED_STOCK: Final = "undated_stock"

DEFAULT_NAME: Final = "Meal plan"
DEFAULT_WEEK_START: Final = "sat"
DEFAULT_MENU_DAYS: Final = 7
DEFAULT_ROLLOVER_DAY: Final = "thu"
DEFAULT_UNDATED_STOCK: Final = True

MIN_MENU_DAYS: Final = 1
MAX_MENU_DAYS: Final = 21

# Weekdays, in the order Python's date.weekday() uses.
WEEKDAYS: Final[tuple[str, ...]] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# The department an unclassified article lands in. Always sorted last.
UNKNOWN_DEPARTMENT: Final = "unknown"

# How often an unknown article must appear before learning it is suggested.
LEARN_SUGGESTION_THRESHOLD: Final = 3

# Fallback cadence when an article has never been bought twice.
DEFAULT_PANTRY_CADENCE_DAYS: Final = 42


class Kind(StrEnum):
    """Why an article ends up on the shopping list."""

    FRESH = "fresh"
    """Because a meal is planned."""

    PANTRY = "pantry"
    """Because it ran low."""


class ShelfLife(StrEnum):
    """How much attention an expiry date deserves."""

    IMPORTANT = "important"
    """Track from the moment it is bought, and ask for it."""

    NEAR_ONLY = "near_only"
    """There is a date, but it is weeks away. Only surface it once it is close."""

    IGNORE = "ignore"
    """Do not track a date at all."""


class Certainty(StrEnum):
    """How sure we are that an ingredient belongs to a dish."""

    CERTAIN = "certain"
    LIKELY = "likely"
    POSSIBLE = "possible"


class IngredientSource(StrEnum):
    """Where the knowledge about an ingredient came from."""

    RECIPE_LIST = "recipe_list"
    DAY_NOTE = "day_note"
    CO_OCCURRENCE = "co_occurrence"
    MANUAL = "manual"


class DepartmentSource(StrEnum):
    """How an article's department was decided."""

    TABLE = "table"
    RULE = "rule"
    FROZEN_MARKER = "frozen_marker"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class StoreSource(StrEnum):
    """How a store's department order was arrived at."""

    DERIVED = "derived"
    """Measured from real lists."""

    FRAMEWORK = "framework"
    """An assumption. Not backed by data."""

    MANUAL = "manual"


class ListName(StrEnum):
    """The three to-do lists this integration owns."""

    SHOPPING = "shopping"
    """This trip."""

    LATER = "later"
    """Next trip. The underlined `later` block that was already on the paper."""

    STOCK = "stock"
    """Perishables worth keeping an eye on. Not a stock count."""


class When(StrEnum):
    """Which shopping trip an article is meant for."""

    NOW = "now"
    LATER = "later"


class EventKind(StrEnum):
    """What happened, in the household's own history.

    The counts and cadences this integration reasons with are all derived from
    these. Until now only `listed` was recorded, under a different name, which
    meant "how often do we buy coffee" was really answering "how often does
    coffee get written down" — close, but not the same question.
    """

    LISTED = "listed"
    """Went onto a list."""

    UNLISTED = "unlisted"
    """Came off a list without being bought."""

    BOUGHT = "bought"
    """Ticked off on a shopping list. This is the one that was missing."""

    EATEN = "eaten"
    """A planned day came and went with a dish on it."""

    CHECKED = "checked"
    """Answered during a round: still enough, or run out."""

    STOCKED = "stocked"
    """Noted as being in the house, with or without a date."""

    USED = "used"
    """Ticked off the stock list. Eaten up, whenever that happened."""


class Round(StrEnum):
    """Which round is being walked.

    Two rounds, the same rhythm, different content: one asks "do we still have
    enough of this?" at a cupboard, the other asks "are these dates still
    right?" at a fridge. Both are answered per article and both can be taken
    back as a whole.
    """

    PANTRY = "pantry"
    FRIDGE = "fridge"


class PantryScope(StrEnum):
    """Which pantry articles to check."""

    GENERAL = "general"
    """Everything that is due by its own cadence."""

    MENU = "menu"
    """The pantry ingredients of the dishes currently planned."""


# Services
SERVICE_ADD_DISH: Final = "add_dish"
SERVICE_RUNNING_LOW: Final = "running_low"
SERVICE_PLAN_MENU: Final = "plan_menu"
SERVICE_COMPLETE_ALL: Final = "complete_all"
SERVICE_SORT_LIST: Final = "sort_list"
SERVICE_SET_EXPIRY: Final = "set_expiry"
SERVICE_LEARN_DISH: Final = "learn_dish"
SERVICE_PRINT_LIST: Final = "print_list"
SERVICE_IMPORT_KNOWLEDGE: Final = "import_knowledge"
SERVICE_EXPORT_KNOWLEDGE: Final = "export_knowledge"

SERVICE_SET_STORE_ORDER: Final = "set_store_order"
SERVICE_CHECK_OFF: Final = "check_off"
SERVICE_RESET_ROUND: Final = "reset_round"
SERVICE_MOVE_ITEM: Final = "move_item"
SERVICE_MOVE_ALL: Final = "move_all"

# Management. Everything the four sets need: add, change, rename, remove, and
# the bin that makes removing safe.
SERVICE_SET_DISH: Final = "set_dish"
SERVICE_REMOVE_DISH: Final = "remove_dish"
SERVICE_REMOVE_ARTICLE: Final = "remove_article"
SERVICE_RENAME_ARTICLE: Final = "rename_article"
SERVICE_MERGE_ARTICLES: Final = "merge_articles"
SERVICE_SET_DEPARTMENT: Final = "set_department"
SERVICE_REMOVE_DEPARTMENT: Final = "remove_department"
SERVICE_SET_STORE: Final = "set_store"
SERVICE_REMOVE_STORE: Final = "remove_store"
SERVICE_RESTORE_DELETED: Final = "restore_deleted"
SERVICE_DISCARD_DELETED: Final = "discard_deleted"
SERVICE_FORGET_EVENTS: Final = "forget_events"
SERVICE_LIST_ARTICLES: Final = "list_articles"
SERVICE_LIST_DEPARTMENTS: Final = "list_departments"
SERVICE_GET_DELETED: Final = "get_deleted"

SERVICE_GET_WEEK: Final = "get_week"
SERVICE_GET_HISTORY: Final = "get_history"
SERVICE_GET_LIST: Final = "get_list"
SERVICE_LIST_DISHES: Final = "list_dishes"
SERVICE_GET_PANTRY_CHECK: Final = "get_pantry_check"
SERVICE_GET_EXPIRING: Final = "get_expiring"
SERVICE_SUGGEST_MENU: Final = "suggest_menu"

# Service fields
ATTR_ARTICLE: Final = "article"
ATTR_ARTICLES: Final = "articles"
ATTR_DATE: Final = "date"
ATTR_DAYS: Final = "days"
ATTR_DEPARTMENTS: Final = "departments"
ATTR_DISH: Final = "dish"
ATTR_ENOUGH: Final = "enough"
ATTR_ENTRY_ID: Final = "entry_id"
ATTR_EXCEPT_ITEMS: Final = "except_items"
ATTR_EXPIRY: Final = "expiry"
ATTR_FROM: Final = "from"
ATTR_INTO: Final = "into"
ATTR_ITEM: Final = "item"
ATTR_LABELS: Final = "labels"
ATTR_MOVE_TO: Final = "move_to"
ATTR_NAME: Final = "name"
ATTR_POSITION: Final = "position"
ATTR_SEARCH: Final = "search"
ATTR_INCLUDE_PANTRY: Final = "include_pantry"
ATTR_INCLUDE_COMPLETED: Final = "include_completed"
ATTR_INGREDIENTS: Final = "ingredients"
ATTR_KIND: Final = "kind"
ATTR_KNOWLEDGE: Final = "knowledge"
ATTR_LIMIT: Final = "limit"
ATTR_LIST: Final = "list"
ATTR_OFFSET: Final = "offset"
ATTR_SINCE: Final = "since"
ATTR_UNTIL: Final = "until"
ATTR_NOTE: Final = "note"
ATTR_PEOPLE: Final = "people"
ATTR_ROUND: Final = "round"
ATTR_SCOPE: Final = "scope"
ATTR_SERVINGS: Final = "servings"
ATTR_START: Final = "start"
ATTR_STORE: Final = "store"
ATTR_TO: Final = "to"
ATTR_WHEN: Final = "when"

# Dispatcher signal fired whenever the stored data changed.
SIGNAL_UPDATED: Final = f"{DOMAIN}_updated"

# HTTP
PRINT_URL: Final = f"/api/{DOMAIN}/print"

# The dashboard cards. One file, served straight from the integration and
# registered as an extra module, so there is no build step and nothing to add
# to the Lovelace resource list by hand.
CARDS_DIR: Final = "www"
CARDS_FILE: Final = "mealplan-cards.js"
CARDS_URL: Final = f"/{DOMAIN}-static"

# Number of days an expiry counts as "urgent" on the dashboard.
URGENT_EXPIRY_DAYS: Final = 2

# How many events one `get_history` call returns by default, and at most. A
# model asking for everything gets it a page at a time rather than a refusal:
# the response carries the total, so it knows whether to ask again.
DEFAULT_HISTORY_LIMIT: Final = 200
MAX_HISTORY_LIMIT: Final = 2000
