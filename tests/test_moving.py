"""Two lists, and the traffic between them.

The paper already had two: what has to come along this trip, and what can wait
for the next one. What it also had — and what the first version of this
integration lost — was the ability to change your mind, by scratching a line out
of one block and writing it in the other. Adding was possible from day one;
moving was not.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import DOMAIN, EventKind, ListName

TODAY = date(2026, 8, 6)


@pytest.fixture(autouse=True)
def _freeze(freezer):
    freezer.move_to("2026-08-06 18:00:00+02:00")


async def call(hass: HomeAssistant, service: str, data: dict[str, Any] | None = None) -> Any:
    return await hass.services.async_call(DOMAIN, service, data or {}, blocking=True, return_response=True)


@pytest.fixture
async def seeded(hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]) -> MockConfigEntry:
    await call(hass, "import_knowledge", {"knowledge": knowledge})
    return entry


def summaries(store, list_name: ListName) -> list[str]:
    return [item.summary for item in store.open_items(list_name)]


async def test_a_whole_list_moves_over_in_one_press(hass: HomeAssistant, seeded: MockConfigEntry):
    """The moment a shopping round starts: the next trip is now this trip."""
    for article in ("rice", "tomatoes", "poultry rub"):
        await call(hass, "running_low", {"article": article, "when": "later"})

    result = await call(hass, "move_all", {"to": "shopping"})

    store = seeded.runtime_data.store
    assert sorted(result["moved"]) == ["poultry rub", "rice", "tomatoes"]
    assert store.open_items(ListName.LATER) == []
    assert sorted(summaries(store, ListName.SHOPPING)) == ["poultry rub", "rice", "tomatoes"]


async def test_moving_a_whole_list_is_not_a_shelf_of_new_listings(hass: HomeAssistant, seeded: MockConfigEntry):
    """Three articles moved must not read as three articles wanted again.

    Everything downstream — cadence, "how often do we buy this", the cupboard
    round — is counted from listings. A move that counted would inflate all of
    it by however often the household reshuffles its two lists.
    """
    for article in ("rice", "tomatoes"):
        await call(hass, "running_low", {"article": article, "when": "later"})
    store = seeded.runtime_data.store
    before = {name: store.article(name).times for name in ("rice", "tomatoes")}

    await call(hass, "move_all", {"to": "shopping"})

    assert {name: store.article(name).times for name in ("rice", "tomatoes")} == before
    assert [event.kind for event in store.data.events].count(EventKind.LISTED) == 2


async def test_moving_a_whole_list_leaves_what_is_already_bought(hass: HomeAssistant, seeded: MockConfigEntry):
    """A ticked-off line is finished business and does not come along."""
    await call(hass, "running_low", {"article": "rice", "when": "later"})
    await call(hass, "running_low", {"article": "tomatoes", "when": "later"})
    store = seeded.runtime_data.store
    bought = store.find_by_summary(ListName.LATER, "rice")
    store.complete_item(ListName.LATER, bought, TODAY)

    result = await call(hass, "move_all", {"to": "shopping"})

    assert result["moved"] == ["tomatoes"]
    assert [item.summary for item in store.items(ListName.LATER) if item.completed] == ["rice"]


async def test_moving_an_empty_list_is_not_an_error(hass: HomeAssistant, seeded: MockConfigEntry):
    """Pressing it twice is a thing people do."""
    assert (await call(hass, "move_all", {"to": "shopping"}))["moved"] == []


async def test_one_item_moves_the_other_way_too(hass: HomeAssistant, seeded: MockConfigEntry):
    """Not everything on today's list has to be bought today."""
    await call(hass, "running_low", {"article": "rice"})

    await call(hass, "move_item", {"item": "rice", "to": "later"})

    store = seeded.runtime_data.store
    assert summaries(store, ListName.SHOPPING) == []
    assert summaries(store, ListName.LATER) == ["rice"]


async def test_an_item_moved_lands_in_the_walking_order(hass: HomeAssistant, seeded: MockConfigEntry):
    """Arriving at the bottom of a sorted list is arriving in the wrong aisle."""
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.meal_plan_store", "option": "Corner Market"}, blocking=True
    )
    await call(hass, "running_low", {"article": "rice"})
    await call(hass, "running_low", {"article": "minced beef", "when": "later"})
    await call(hass, "running_low", {"article": "tomatoes", "when": "later"})

    await call(hass, "move_all", {"to": "shopping"})

    # produce, then butcher, then dry goods — the route of this shop.
    assert summaries(seeded.runtime_data.store, ListName.SHOPPING) == ["tomatoes", "minced beef", "rice"]


async def test_moving_something_already_there_changes_nothing(hass: HomeAssistant, seeded: MockConfigEntry):
    """Not an error and not a duplicate: it is where it was asked to be."""
    await call(hass, "running_low", {"article": "rice"})

    result = await call(hass, "move_item", {"item": "rice", "to": "shopping"})

    assert result["moved"] is False
    assert summaries(seeded.runtime_data.store, ListName.SHOPPING) == ["rice"]


async def test_a_moved_item_keeps_everything_that_was_on_it(hass: HomeAssistant, seeded: MockConfigEntry):
    """The dish it came from, the shop it is only sold in, the note, the uid.

    It is the same item on another list, so it has to arrive as itself — a card
    that reopened a menu by uid after a move would otherwise find nothing.
    """
    await call(hass, "add_dish", {"dish": "tacos", "include_pantry": True})
    store = seeded.runtime_data.store
    rub = next(item for item in store.open_items(ListName.SHOPPING) if item.summary == "poultry rub")
    uid, dish, availability = rub.uid, rub.dish, rub.availability

    await call(hass, "move_item", {"item": uid, "to": "later"})

    moved = store.open_items(ListName.LATER)[0]
    assert (moved.uid, moved.dish, moved.availability) == (uid, dish, availability)
    assert moved.added_on == TODAY


async def test_moving_by_name_finds_it_wherever_it_is(hass: HomeAssistant, seeded: MockConfigEntry):
    """Assist gets a name, not a uid, and the household does not know its lists apart."""
    await call(hass, "add_stock", {"article": "minced beef", "expiry": "2026-08-08"})

    await call(hass, "move_item", {"item": "minced beef", "to": "shopping"})

    store = seeded.runtime_data.store
    assert summaries(store, ListName.STOCK) == []
    assert summaries(store, ListName.SHOPPING) == ["minced beef"]


async def test_asking_to_move_something_unknown_says_so(hass: HomeAssistant, seeded: MockConfigEntry):
    """Silence would look exactly like a move that worked."""
    with pytest.raises(ServiceValidationError):
        await call(hass, "move_item", {"item": "a hyacinth", "to": "later"})


async def test_renaming_a_line_does_not_rename_the_article(hass: HomeAssistant, seeded: MockConfigEntry):
    """A typo on today's list is a typo on today's list.

    Renaming the article everywhere is a heavier act with a longer reach, and it
    belongs on the management screen rather than behind a tap on a row.
    """
    await call(hass, "running_low", {"article": "tomatoes"})
    store = seeded.runtime_data.store
    item = store.open_items(ListName.SHOPPING)[0]

    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": "todo.meal_plan_shopping_list", "item": item.uid, "rename": "tomatoes (tin)"},
        blocking=True,
    )

    assert summaries(store, ListName.SHOPPING) == ["tomatoes (tin)"]
    assert store.article("tomatoes") is not None
    assert store.article("tomatoes (tin)") is None
    assert store.open_items(ListName.SHOPPING)[0].article == "tomatoes", "still the same article underneath"


async def test_filing_a_line_under_another_department_moves_every_copy(hass: HomeAssistant, seeded: MockConfigEntry):
    """The row menu's department picker is `learn_article`, and it reaches.

    Correcting a heading is only worth doing if it is the last time you have to
    do it, so it lands on the article and on every list at once.
    """
    await call(hass, "running_low", {"article": "rice"})
    await call(hass, "running_low", {"article": "rice", "when": "later"})

    await call(hass, "learn_article", {"article": "rice", "department": "produce"})

    store = seeded.runtime_data.store
    assert store.article("rice").department == "produce"
    assert {item.department for item in store.open_items(ListName.SHOPPING)} == {"produce"}
    assert {item.department for item in store.open_items(ListName.LATER)} == {"produce"}
    assert str(store.article("rice").department_source) == "manual", "and an import will not undo it"
