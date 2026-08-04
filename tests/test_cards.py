"""What the dashboard cards stand on.

The cards are the only part of this integration with no test harness of its
own: it runs in a browser. So the contract underneath them is tested here
instead — the grouped list, the walking route you can correct in the aisle, and
the entity ids the cards need in order to tick something off. Break one of
these and a card breaks silently, on a phone, in a shop.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import DOMAIN, UNKNOWN_DEPARTMENT, ListName

THURSDAY = date(2026, 8, 6)


@pytest.fixture(autouse=True)
def _freeze(freezer):
    """The same Thursday evening as the scenarios."""
    freezer.move_to("2026-08-06 18:00:00+02:00")


@pytest.fixture
async def seeded(hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]) -> MockConfigEntry:
    """A seeded meal plan with a store selected, as a dashboard would find it."""
    await hass.config.async_update(language="nl")
    await hass.services.async_call(
        DOMAIN, "import_knowledge", {"knowledge": knowledge}, blocking=True, return_response=True
    )
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.meal_plan_store", "option": "Corner Market"}, blocking=True
    )
    await hass.async_block_till_done()
    return entry


async def call(hass: HomeAssistant, service: str, data: dict[str, Any] | None = None) -> Any:
    """Call one of our services and return its response."""
    return await hass.services.async_call(DOMAIN, service, data or {}, blocking=True, return_response=True)


# ------------------------------------------------------------------- get_list


async def test_get_list_groups_by_department_in_walking_order(hass: HomeAssistant, seeded: MockConfigEntry):
    """The headings are the point. A flat list is what the paper already beat."""
    await call(hass, "running_low", {"article": "rice"})
    await call(hass, "running_low", {"article": "minced beef"})
    await call(hass, "running_low", {"article": "tomatoes"})
    await call(hass, "sort_list")

    result = await call(hass, "get_list")

    assert [group["department"] for group in result["groups"]] == ["produce", "butcher", "dry_goods"]
    assert [group["label"] for group in result["groups"]] == ["Groenten & fruit", "Beenhouwerij", "Droge voeding"]
    assert [item["summary"] for group in result["groups"] for item in group["items"]] == [
        "tomatoes",
        "minced beef",
        "rice",
    ]
    assert result["open"] == 3
    assert result["store"] == "Corner Market"


async def test_get_list_puts_the_unclassified_bucket_last(hass: HomeAssistant, seeded: MockConfigEntry):
    """Free text goes on the list without a question, and lands at the bottom."""
    await call(hass, "running_low", {"article": "tomatoes"})
    await call(hass, "running_low", {"article": "birthday candles"})
    await call(hass, "sort_list")

    result = await call(hass, "get_list")

    assert result["groups"][-1]["department"] == UNKNOWN_DEPARTMENT
    assert result["groups"][-1]["label"] == "Nog iets"
    assert [item["summary"] for item in result["groups"][-1]["items"]] == ["birthday candles"]


async def test_get_list_carries_what_a_card_has_to_show(hass: HomeAssistant, seeded: MockConfigEntry):
    """A uid to tick it off with, the shop it is only sold in, and the days left."""
    await call(hass, "add_stock", {"article": "minced beef", "expiry": "2026-08-08"})
    await call(hass, "running_low", {"article": "poultry rub"})

    shopping = await call(hass, "get_list", {"list": str(ListName.SHOPPING)})
    rub = shopping["groups"][0]["items"][0]
    assert rub["availability"] == "Big Barn"
    assert rub["uid"]

    stock = await call(hass, "get_list", {"list": str(ListName.STOCK)})
    beef = stock["groups"][0]["items"][0]
    assert beef["due"] == "2026-08-08"
    assert beef["days_left"] == 2


async def test_get_list_hides_completed_items_unless_asked(hass: HomeAssistant, seeded: MockConfigEntry):
    """Ticked-off items leave the list but stay counted, so nothing looks lost."""
    await call(hass, "running_low", {"article": "tomatoes"})
    await call(hass, "complete_all")

    result = await call(hass, "get_list")
    assert result["groups"] == []
    assert result["open"] == 0
    assert result["completed"] == 1

    with_done = await call(hass, "get_list", {"include_completed": True})
    assert [item["summary"] for group in with_done["groups"] for item in group["items"]] == ["tomatoes"]


# ------------------------------------------------------------ set_store_order


async def test_set_store_order_reorders_the_open_list_immediately(hass: HomeAssistant, seeded: MockConfigEntry):
    """Corrected in the aisle, so it has to take effect in the aisle."""
    for article in ("rice", "minced beef", "tomatoes"):
        await call(hass, "running_low", {"article": article})
    await call(hass, "sort_list")
    assert [item.summary for item in seeded.runtime_data.store.open_items(ListName.SHOPPING)] == [
        "tomatoes",
        "minced beef",
        "rice",
    ]

    await call(hass, "set_store_order", {"departments": ["dry_goods", "butcher", "produce"]})

    assert [item.summary for item in seeded.runtime_data.store.open_items(ListName.SHOPPING)] == [
        "rice",
        "minced beef",
        "tomatoes",
    ]


async def test_set_store_order_keeps_what_you_left_out(hass: HomeAssistant, seeded: MockConfigEntry):
    """Moving one department up is a complete instruction, not half a permutation."""
    result = await call(hass, "set_store_order", {"departments": ["dry_goods"]})

    assert result["department_order"][0] == "dry_goods"
    assert set(result["department_order"]) == set(seeded.runtime_data.store.department_keys)


async def test_set_store_order_only_touches_the_store_you_name(hass: HomeAssistant, seeded: MockConfigEntry):
    """Another shop's route is not evidence about this one."""
    await call(hass, "set_store_order", {"departments": ["dry_goods"], "store": "Big Barn"})

    assert seeded.runtime_data.store.store_order("Big Barn")[0] == "dry_goods"
    assert seeded.runtime_data.store.store_order("Corner Market")[0] == "produce"


async def test_set_store_order_refuses_a_department_that_does_not_exist(hass: HomeAssistant, seeded: MockConfigEntry):
    """A typo would silently drop a heading off the list."""
    with pytest.raises(ServiceValidationError):
        await call(hass, "set_store_order", {"departments": ["bakery_aisle_7"]})


async def test_picking_a_store_reorders_the_list_and_the_headings(hass: HomeAssistant, seeded: MockConfigEntry):
    """Picking the shop is the whole point of the selector.

    A list still in the previous shop's walking route, or headings that lag a
    tap behind, is worse than no order at all.
    """
    await call(hass, "set_store_order", {"departments": ["dry_goods", "butcher", "produce"], "store": "Big Barn"})
    for article in ("rice", "tomatoes"):
        await call(hass, "running_low", {"article": article})

    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.meal_plan_store", "option": "Big Barn"}, blocking=True
    )
    await hass.async_block_till_done()

    assert [item.summary for item in seeded.runtime_data.store.open_items(ListName.SHOPPING)] == ["rice", "tomatoes"]
    attributes = hass.states.get("sensor.meal_plan_summary").attributes
    assert attributes["store"] == "Big Barn"
    assert [department["key"] for department in attributes["departments"]][:3] == ["dry_goods", "butcher", "produce"]


# --------------------------------------------------------------- the contract


async def test_summary_names_the_other_entities(hass: HomeAssistant, seeded: MockConfigEntry):
    """Entity ids are localised. A card that guesses them breaks in someone else's house."""
    attributes = hass.states.get("sensor.meal_plan_summary").attributes

    assert attributes["entry_id"] == seeded.entry_id
    assert attributes["entities"]["shopping"] == "todo.meal_plan_shopping_list"
    assert attributes["entities"]["later"] == "todo.meal_plan_next_trip"
    assert attributes["entities"]["stock"] == "todo.meal_plan_in_the_house"
    assert attributes["entities"]["calendar"] == "calendar.meal_plan_meal_plan"
    assert attributes["entities"]["store"] == "select.meal_plan_store"


async def test_the_card_bundle_ships_with_the_integration(hass: HomeAssistant):
    """Cards nobody has to install by hand are cards that cannot go stale."""
    from pathlib import Path

    import custom_components.mealplan as integration
    from custom_components.mealplan.const import CARDS_DIR, CARDS_FILE

    bundle = Path(integration.__file__).parent / CARDS_DIR / CARDS_FILE
    assert bundle.exists()
    source = bundle.read_text(encoding="utf-8")
    for element in ("mealplan-menu-card", "mealplan-list-card", "mealplan-round-card", "mealplan-route-card"):
        assert f'"{element}"' in source
