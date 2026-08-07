"""What the household remembers.

Everything this integration reasons with — cadences, frequencies, "when did we
last" — is derived from these events. Until they existed, the only thing ever
recorded was that something had been *written down*, and every measurement
quietly answered a slightly different question than the one asked.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
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


def kinds_of(store, article: str) -> list[str]:
    return [event.kind for event in store.data.events if event.article == article]


async def test_buying_is_recorded_and_not_only_listing(hass: HomeAssistant, seeded: MockConfigEntry):
    """The gap this whole file exists to close.

    Cadence was measured on "went onto a list", which is a near miss: things get
    written down and then not bought. Now both are recorded, separately.
    """
    store = seeded.runtime_data.store
    await call(hass, "running_low", {"article": "rice"})
    assert kinds_of(store, "rice") == [EventKind.LISTED]

    await call(hass, "complete_all")

    assert kinds_of(store, "rice") == [EventKind.LISTED, EventKind.BOUGHT]
    bought = next(e for e in store.data.events if e.kind == EventKind.BOUGHT)
    assert bought.on == TODAY
    assert bought.detail["list"] == "shopping"


async def test_ticking_off_through_the_todo_entity_counts_too(hass: HomeAssistant, seeded: MockConfigEntry):
    """Most ticking off happens from a card, not from the bulk service."""
    store = seeded.runtime_data.store
    await call(hass, "running_low", {"article": "tomatoes"})
    item = store.open_items(ListName.SHOPPING)[0]

    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": "todo.meal_plan_shopping_list", "item": item.uid, "status": "completed"},
        blocking=True,
    )

    assert EventKind.BOUGHT in kinds_of(store, "tomatoes")


async def test_taken_off_without_being_bought_is_a_different_fact(hass: HomeAssistant, seeded: MockConfigEntry):
    """Written down and then dropped is not the same as written down and bought.

    Without the distinction, a change of mind looks exactly like a purchase and
    the cadence learns the wrong thing.
    """
    store = seeded.runtime_data.store
    await call(hass, "running_low", {"article": "poultry rub"})
    item = store.open_items(ListName.SHOPPING)[0]

    await hass.services.async_call(
        "todo",
        "remove_item",
        {"entity_id": "todo.meal_plan_shopping_list", "item": item.uid},
        blocking=True,
    )

    assert kinds_of(store, "poultry rub") == [EventKind.LISTED, EventKind.UNLISTED]


async def test_the_stock_list_tells_the_other_end_of_the_story(hass: HomeAssistant, seeded: MockConfigEntry):
    """Ticking off stock means used up, not bought."""
    store = seeded.runtime_data.store
    await call(hass, "add_stock", {"article": "minced beef", "expiry": "2026-08-08"})
    assert kinds_of(store, "minced beef") == [EventKind.STOCKED]

    item = store.open_items(ListName.STOCK)[0]
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": "todo.meal_plan_in_the_house", "item": item.uid, "status": "completed"},
        blocking=True,
    )

    used = next(e for e in store.data.events if e.kind == EventKind.USED)
    assert used.article == "minced beef"
    assert used.detail["due"] == "2026-08-08", "the date rides along as a fact"


async def test_a_late_tick_off_draws_no_conclusion(hass: HomeAssistant, seeded: MockConfigEntry):
    """Something ticked off after its date was eaten late, not thrown away.

    The facts are kept — the date it carried and the day it went — and no
    verdict is attached to them.
    """
    store = seeded.runtime_data.store
    await call(hass, "add_stock", {"article": "tomatoes", "expiry": "2026-08-01"})
    item = store.open_items(ListName.STOCK)[0]
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": "todo.meal_plan_in_the_house", "item": item.uid, "status": "completed"},
        blocking=True,
    )

    used = next(e for e in store.data.events if e.kind == EventKind.USED)
    assert used.on == TODAY
    assert used.detail["due"] == "2026-08-01"
    assert "wasted" not in used.detail
    assert "late" not in used.detail


async def test_a_day_that_has_passed_becomes_a_fact(hass: HomeAssistant, seeded: MockConfigEntry):
    """A plan can be edited afterwards; what was on the table cannot.

    So once the day is behind us it is written down, and the plan is then free
    to change without rewriting history.
    """
    store = seeded.runtime_data.store
    await call(hass, "plan_menu", {"date": "2026-08-03", "dish": "tacos", "people": 4})
    await call(hass, "plan_menu", {"date": "2026-08-20", "dish": "rice"})

    eaten = [e for e in store.data.events if e.kind == EventKind.EATEN]
    assert [(e.dish, e.on.isoformat()) for e in eaten] == [("tacos", "2026-08-03")]
    assert eaten[0].detail["people"] == 4

    # Clearing the day afterwards leaves the fact standing, and re-running does
    # not record it twice.
    await call(hass, "plan_menu", {"date": "2026-08-03", "clear": True})
    assert len([e for e in store.data.events if e.kind == EventKind.EATEN]) == 1


# ------------------------------------------------------------------ reading


async def test_history_answers_the_everyday_question(hass: HomeAssistant, seeded: MockConfigEntry):
    """When did we last buy rice — without handing over the whole blob."""
    await call(hass, "running_low", {"article": "rice"})
    await call(hass, "running_low", {"article": "tomatoes"})
    await call(hass, "complete_all")

    result = await call(hass, "get_history", {"article": "rice", "kind": "bought"})

    assert result["total"] == 1
    assert result["events"][0]["article"] == "rice"
    assert result["events"][0]["kind"] == "bought"


async def test_history_hands_over_everything_a_page_at_a_time(hass: HomeAssistant, seeded: MockConfigEntry):
    """A model that wants all of it gets all of it, in a shape it can survive."""
    for article in ("rice", "tomatoes", "minced beef", "poultry rub"):
        await call(hass, "running_low", {"article": article})

    first = await call(hass, "get_history", {"limit": 2})
    assert first["total"] == 4
    assert first["returned"] == 2
    assert first["offset"] == 0

    second = await call(hass, "get_history", {"limit": 2, "offset": 2})
    assert second["returned"] == 2

    seen = [e["article"] for e in first["events"] + second["events"]]
    assert sorted(seen) == ["minced beef", "poultry rub", "rice", "tomatoes"]


async def test_history_is_newest_first(hass: HomeAssistant, seeded: MockConfigEntry, freezer):
    """Questions about a household's past are almost always about its recent past."""
    freezer.move_to("2026-07-01 12:00:00+02:00")
    await call(hass, "running_low", {"article": "rice"})
    freezer.move_to("2026-08-06 18:00:00+02:00")
    await call(hass, "running_low", {"article": "tomatoes"})

    result = await call(hass, "get_history", {"kind": "listed"})
    assert [e["article"] for e in result["events"]] == ["tomatoes", "rice"]


async def test_history_survives_a_round_trip_and_does_not_double(
    hass: HomeAssistant, seeded: MockConfigEntry, knowledge: dict[str, Any]
):
    """An export taken yesterday must not erase — or duplicate — what happened since."""
    await call(hass, "running_low", {"article": "rice"})
    exported = await call(hass, "export_knowledge")
    assert len(exported["events"]) == 1

    await call(hass, "import_knowledge", {"knowledge": exported})
    again = await call(hass, "get_history")
    assert again["total"] == 1, "importing its own export changes nothing"
