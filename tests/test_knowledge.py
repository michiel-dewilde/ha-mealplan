"""Importing and exporting the knowledge file."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import DOMAIN


@pytest.fixture(autouse=True)
def _freeze(freezer):
    freezer.move_to("2026-08-06 18:00:00+02:00")


async def call(hass: HomeAssistant, service: str, data: dict[str, Any] | None = None) -> Any:
    return await hass.services.async_call(DOMAIN, service, data or {}, blocking=True, return_response=True)


async def test_import_seeds_everything(hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]):
    result = await call(hass, "import_knowledge", {"knowledge": knowledge})
    assert result == {"departments": 13, "stores": 1, "articles": 4, "dishes": 2}

    store = entry.runtime_data.store
    assert store.data.stores["Corner Market"].department_order == ["produce", "butcher", "dry_goods"]
    assert store.article("minced beef").shelf_life == "important"
    assert store.dish("tacos").usual_day == "fri"


async def test_import_merges_departments_rather_than_replacing_them(
    hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]
):
    """A file that never mentions `pet` must not delete `pet`.

    The department list is user data from the moment it is first seeded.
    """
    await call(hass, "import_knowledge", {"knowledge": knowledge})
    store = entry.runtime_data.store

    assert store.department("pet") is not None
    assert store.department_keys[:3] == ["produce", "butcher", "dry_goods"], "the file sets the order"


async def test_import_can_replace_when_asked(hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]):
    await call(hass, "import_knowledge", {"knowledge": knowledge, "replace": True})
    assert entry.runtime_data.store.department_keys == ["produce", "butcher", "dry_goods"]


async def test_a_future_schema_is_refused_rather_than_half_read(
    hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]
):
    with pytest.raises(ServiceValidationError):
        await call(hass, "import_knowledge", {"knowledge": {**knowledge, "schema": "3.0"}})


async def test_export_round_trips(hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]):
    await call(hass, "import_knowledge", {"knowledge": knowledge})
    exported = await call(hass, "export_knowledge")

    assert exported["schema"] == "2.0"
    assert {a["name"] for a in exported["articles"]} == {"minced beef", "tomatoes", "rice", "poultry rub"}
    assert {d["name"] for d in exported["dishes"]} == {"tacos", "rice"}

    # And it can be read straight back in.
    result = await call(hass, "import_knowledge", {"knowledge": exported})
    assert result["articles"] == 4


async def test_export_carries_what_has_happened_since_seeding(
    hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]
):
    """Seeded history plus live history — otherwise "last eaten" ages from day one."""
    await call(hass, "import_knowledge", {"knowledge": knowledge})
    await call(hass, "plan_menu", {"date": "2026-08-05", "dish": "tacos"})

    exported = await call(hass, "export_knowledge")
    taco = next(d for d in exported["dishes"] if d["name"] == "tacos")

    assert taco["times"] == 19, "18 seeded plus one planned"
    assert taco["last"] == "2026-08-05", "later than the seeded 2026-07-24"


async def test_free_text_survives_the_round_trip(
    hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]
):
    """Field names are a contract; the content is the household's own words."""
    await call(hass, "import_knowledge", {"knowledge": knowledge})
    exported = await call(hass, "export_knowledge")

    assert "Corner Market" in exported["stores"]
    assert next(d for d in exported["departments"] if d["key"] == "produce")["labels"]["nl"] == ("Groenten & fruit")
    assert next(a for a in exported["articles"] if a["name"] == "poultry rub")["availability"] == "Big Barn"
