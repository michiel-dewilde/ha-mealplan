"""The integration has to be fully usable with nothing seeded.

Someone installing this from HACS does not have forty weeks of handwritten
lists. They get sixteen departments and nothing else, and that has to be a
working integration rather than a broken one. It is also the honest test of the
core: anything that only works with a seeded knowledge base has its intelligence
in the wrong place.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import DOMAIN, UNKNOWN_DEPARTMENT, ListName


@pytest.fixture(autouse=True)
def _freeze(freezer):
    freezer.move_to("2026-08-06 18:00:00+02:00")


async def call(hass: HomeAssistant, service: str, data: dict[str, Any] | None = None) -> Any:
    return await hass.services.async_call(DOMAIN, service, data or {}, blocking=True, return_response=True)


async def test_starts_with_the_default_departments_and_nothing_else(hass: HomeAssistant, entry: MockConfigEntry):
    store = entry.runtime_data.store
    assert len(store.data.departments) == 16
    assert store.department("produce") is not None
    assert store.data.articles == {}
    assert store.data.dishes == {}
    assert store.data.stores == {}


async def test_frozen_behaves_like_a_cupboard_and_not_like_a_meal(hass: HomeAssistant, entry: MockConfigEntry):
    """Frozen peas go on the list because they ran out, not because a meal was planned.

    As `fresh` they were added silently when planning a dish and never turned up
    in the cupboard round. Both of those were wrong, and neither was visible
    from the label.
    """
    store = entry.runtime_data.store
    assert store.department("frozen").kind == "pantry"
    assert store.department("veggie").kind == "fresh", "the split kept the fresh side fresh"


async def test_a_shopping_list_still_works(hass: HomeAssistant, entry: MockConfigEntry):
    """Type it, it is on the list. No department, no question."""
    store = entry.runtime_data.store
    for article in ("bread", "milk", "oranges"):
        await call(hass, "running_low", {"article": article})

    assert [item.summary for item in store.open_items(ListName.SHOPPING)] == [
        "bread",
        "milk",
        "oranges",
    ]
    assert all(item.department == UNKNOWN_DEPARTMENT for item in store.open_items(ListName.SHOPPING))

    result = await call(hass, "complete_all", {"except_items": ["milk"]})
    assert result["kept"] == ["milk"]


async def test_a_menu_still_works(hass: HomeAssistant, entry: MockConfigEntry):
    await call(hass, "plan_menu", {"date": "2026-08-08", "dish": "something with chicken", "note": "visitors"})
    week = await call(hass, "get_week")
    saturday = next(day for day in week["days"] if day["date"] == "2026-08-08")
    assert saturday["dish"] == "something with chicken"
    assert saturday["note"] == "visitors"


async def test_knowledge_grows_as_you_use_it(hass: HomeAssistant, entry: MockConfigEntry):
    """Learn a dish, place its articles, and it behaves like a seeded one."""
    store = entry.runtime_data.store

    await call(
        hass,
        "learn_dish",
        {"dish": "spaghetti", "ingredients": ["minced beef", "spaghetti", "passata"], "usual_day": "mon"},
    )
    await call(hass, "learn_article", {"article": "minced beef", "department": "butcher"})
    await call(hass, "learn_article", {"article": "spaghetti", "department": "dry_goods"})
    await call(hass, "learn_article", {"article": "passata", "department": "preserves"})

    result = await call(hass, "add_dish", {"dish": "spaghetti"})
    assert result["added"] == ["minced beef"]
    assert sorted(result["pantry"]) == ["passata", "spaghetti"]

    dishes = await call(hass, "list_dishes")
    assert dishes["dishes"][0]["usual_day"] == "mon"

    printed = await call(hass, "print_list")
    assert "Butcher" in printed["html"]
    assert store.article("minced beef").department == "butcher"


async def test_suggestions_degrade_gracefully(hass: HomeAssistant, entry: MockConfigEntry):
    """With nothing known there is nothing to suggest — and that is not a crash."""
    result = await call(hass, "suggest_menu")
    assert all(day["candidates"] == [] for day in result["suggestions"])

    assert await call(hass, "get_pantry_check") == {"scope": "general", "checked_today": 0, "articles": []}
    assert (await call(hass, "get_expiring"))["articles"] == []


async def test_printing_an_empty_list(hass: HomeAssistant, entry: MockConfigEntry):
    printed = await call(hass, "print_list")
    assert "Nothing on the list." in printed["html"]
