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
    assert result == {"departments": 13, "stores": 1, "articles": 4, "dishes": 2, "kept_manual": []}

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

    assert exported["schema"] == "2.1"
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


async def test_import_adopts_ingredients_that_are_not_listed_as_articles(
    hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]
):
    """A recipe can name something the shopping list never has under that name.

    Without adopting those, the ingredient lands in `unknown` at the bottom of
    the list even though the file said exactly which department it belongs to.
    """
    knowledge["dishes"][0]["ingredients"].append(
        {"article": "lime", "certainty": "certain", "source": "recipe_list", "department": "produce"}
    )
    await call(hass, "import_knowledge", {"knowledge": knowledge})

    store = entry.runtime_data.store
    assert store.article("lime") is not None
    assert store.article("lime").department == "produce"
    assert store.article_kind("lime") == "fresh"

    result = await call(hass, "add_dish", {"dish": "tacos"})
    assert "lime" in result["added"], "and it is placed, not dumped at the bottom"


async def test_unclassified_items_get_a_readable_heading(hass: HomeAssistant, entry: MockConfigEntry):
    """A heading of UNKNOWN reads like a fault. It is just everything else."""
    store = entry.runtime_data.store
    assert store.department_label("unknown", "en") == "Anything else"
    assert store.department_label("unknown", "nl") == "Nog iets"


async def test_import_places_articles_that_were_typed_before_they_were_known(
    hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]
):
    """Something typed onto a list once sits in `unknown` until someone says otherwise.

    A knowledge file naming its department is exactly that moment. Anything
    already classified is left alone: a decision already made outranks a
    recipe's opinion.
    """
    store = entry.runtime_data.store
    await call(hass, "running_low", {"article": "lime"})
    assert store.article("lime").department == "unknown"

    await call(hass, "learn_article", {"article": "salt", "department": "dry_goods"})
    knowledge["dishes"][0]["ingredients"] += [
        {"article": "lime", "certainty": "certain", "source": "recipe_list", "department": "produce"},
        {"article": "salt", "certainty": "certain", "source": "recipe_list", "department": "preserves"},
    ]
    await call(hass, "import_knowledge", {"knowledge": knowledge})

    assert store.article("lime").department == "produce", "the unclassified one is placed"
    assert store.article("salt").department == "dry_goods", "the classified one is left alone"


async def test_import_never_overwrites_what_was_placed_by_hand(
    hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]
):
    """A file is an opinion; `manual` is a decision.

    Without this, every regenerated knowledge base silently undoes the work done
    in the management screen — and silently is the worst way to lose it.
    """
    store = entry.runtime_data.store
    await call(hass, "import_knowledge", {"knowledge": knowledge})

    await call(
        hass,
        "learn_article",
        {"article": "rice", "department": "produce", "staple": False, "availability": "Big Barn"},
    )
    assert store.article("rice").department == "produce"

    result = await call(hass, "import_knowledge", {"knowledge": knowledge})

    assert store.article("rice").department == "produce", "the file does not win"
    assert store.article("rice").availability == "Big Barn"
    assert store.article("rice").staple is False
    assert result["kept_manual"] == ["rice"], "and it says so rather than pretending it imported"
    assert store.article("tomatoes").department == "produce", "everything else is imported as usual"


async def test_a_protected_article_still_takes_the_higher_counts(
    hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]
):
    """Protecting a decision is not the same as freezing the history.

    The department is the user's; how often the article has been bought and when
    it was last seen are measurements, and a seeded file may know more of them
    than this installation has lived through.
    """
    store = entry.runtime_data.store
    await call(hass, "learn_article", {"article": "rice", "department": "produce"})
    assert store.article("rice").times == 0

    await call(hass, "import_knowledge", {"knowledge": knowledge})

    assert store.article("rice").department == "produce", "still theirs"
    assert store.article("rice").times == 6, "but the count comes along"
    assert store.article("rice").last_listed.isoformat() == "2026-06-01"
