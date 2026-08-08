"""Putting things right.

Everything the integration knows, it learned by watching — and watching gets
things wrong. Two spellings of one article, an ingredient that crept into a dish
because it happened to be on the same list twice, a department that turned out
to describe a fridge rather than what is in it. Without a way to correct those,
a knowledge base only ever gets messier, and the only remedy left is to throw it
away and start again.

So: add, change, rename, merge, remove — and a bin, because deleting is the one
act you cannot inspect afterwards to see whether you meant it.
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


def names_in(result: dict[str, Any]) -> list[str]:
    return [row["article"] for row in result["articles"]]


# --------------------------------------------------------------------- dishes


async def test_setting_a_dish_takes_an_ingredient_back_out(hass: HomeAssistant, seeded: MockConfigEntry):
    """`learn_dish` only ever adds, so a dish that picked up a wrong ingredient kept it.

    Co-occurrence is a good guess and a guess is sometimes wrong; without a way
    to say "no, not that", every wrong guess is permanent.
    """
    before = await call(hass, "list_dishes")
    tacos = next(dish for dish in before["dishes"] if dish["name"] == "tacos")
    assert "tomatoes" in tacos["fresh"]

    await call(hass, "set_dish", {"dish": "tacos", "ingredients": ["minced beef", "poultry rub"]})

    after = await call(hass, "list_dishes")
    tacos = next(dish for dish in after["dishes"] if dish["name"] == "tacos")
    assert sorted(tacos["fresh"] + tacos["pantry"]) == ["minced beef", "poultry rub"]


async def test_setting_a_dish_leaves_what_was_measured_alone(hass: HomeAssistant, seeded: MockConfigEntry):
    """How often it was eaten and when are facts about the household, not about this edit."""
    store = seeded.runtime_data.store
    before = (store.dish("tacos").times, store.dish("tacos").last)

    await call(hass, "set_dish", {"dish": "tacos", "ingredients": ["minced beef"], "usual_day": "sat"})

    assert (store.dish("tacos").times, store.dish("tacos").last) == before
    assert store.dish("tacos").usual_day == "sat"


async def test_setting_a_dish_keeps_what_was_known_about_an_ingredient_that_stays(
    hass: HomeAssistant, seeded: MockConfigEntry
):
    """Re-listing an ingredient is not re-teaching it: its certainty and source survive."""
    store = seeded.runtime_data.store
    await call(hass, "set_dish", {"dish": "tacos", "ingredients": ["tomatoes", "minced beef"]})

    tomatoes = next(i for i in store.dish("tacos").ingredients if i.article == "tomatoes")
    assert str(tomatoes.certainty) == "likely", "it was a guess before and it still is"
    assert str(tomatoes.source) == "co_occurrence"


async def test_a_removed_dish_goes_to_the_bin_and_comes_back_whole(hass: HomeAssistant, seeded: MockConfigEntry):
    """Deleting is the one act you cannot look at afterwards to see whether you meant it."""
    await call(hass, "remove_dish", {"dish": "tacos"})
    assert seeded.runtime_data.store.dish("tacos") is None
    assert [entry["name"] for entry in (await call(hass, "get_deleted"))["deleted"]] == ["tacos"]

    await call(hass, "restore_deleted", {"name": "tacos", "kind": "dish"})

    dish = seeded.runtime_data.store.dish("tacos")
    assert dish is not None
    assert dish.times == 18
    assert [i.article for i in dish.ingredients] == ["minced beef", "tomatoes", "poultry rub"]
    assert (await call(hass, "get_deleted"))["deleted"] == []


async def test_removing_a_dish_leaves_the_days_it_was_eaten_on(hass: HomeAssistant, seeded: MockConfigEntry):
    """What was on the table is a fact and does not become untrue when the recipe is tidied away."""
    await call(hass, "plan_menu", {"date": "2026-08-03", "dish": "tacos"})

    await call(hass, "remove_dish", {"dish": "tacos"})

    eaten = [e for e in seeded.runtime_data.store.data.events if e.kind == EventKind.EATEN]
    assert [e.dish for e in eaten] == ["tacos"]


# ------------------------------------------------------------------- articles


async def test_renaming_an_article_takes_its_history_with_it(hass: HomeAssistant, seeded: MockConfigEntry):
    """A rename that stopped at the article table would make it look brand new.

    Every count and every cadence is read back out of the events, so leaving
    them behind would silently reset the article's whole history — and the
    cupboard round would start asking about it again the next day.
    """
    await call(hass, "running_low", {"article": "rice"})
    store = seeded.runtime_data.store

    result = await call(hass, "rename_article", {"article": "rice", "to": "basmati"})

    assert result["merged"] is False
    assert store.article("rice") is None
    assert store.article("basmati").times == 7, "six seeded plus the one just listed"
    assert store.last_listed("basmati") == TODAY
    assert [e.article for e in store.data.events if e.kind == EventKind.LISTED] == ["basmati"]
    assert [i.summary for i in store.open_items(ListName.SHOPPING)] == ["basmati"]


async def test_renaming_an_article_reaches_into_the_dishes_that_use_it(hass: HomeAssistant, seeded: MockConfigEntry):
    """A dangling ingredient is a dish that quietly stopped knowing what goes in it."""
    await call(hass, "rename_article", {"article": "minced beef", "to": "mince"})

    tacos = next(d for d in (await call(hass, "list_dishes"))["dishes"] if d["name"] == "tacos")
    assert "mince" in tacos["fresh"]
    assert "minced beef" not in tacos["fresh"] + tacos["pantry"] + tacos["unclassified"]


async def test_renaming_onto_a_name_that_exists_is_a_merge(hass: HomeAssistant, seeded: MockConfigEntry):
    """Two ways to say the same thing should not need two code paths that agree."""
    result = await call(hass, "rename_article", {"article": "tomatoes", "to": "rice"})

    assert result["merged"] is True
    assert seeded.runtime_data.store.article("rice").times == 15, "nine plus six"


async def test_merging_adds_the_histories_and_keeps_the_later_date(hass: HomeAssistant, seeded: MockConfigEntry):
    """Two spellings each carry half a history, which makes both look rarer than the thing is.

    The date is the later of the two: "last listed" is the most recent time
    either spelling was written down, and taking the earlier would say the
    article is more overdue than it is.
    """
    store = seeded.runtime_data.store
    assert store.article("minced beef").last_listed == date(2026, 7, 30)
    assert store.article("tomatoes").last_listed == date(2026, 7, 25)

    result = await call(hass, "merge_articles", {"article": "tomatoes", "into": "minced beef"})

    assert result["times"] == 22, "thirteen plus nine"
    assert store.article("minced beef").last_listed == date(2026, 7, 30)
    assert store.article("tomatoes") is None


async def test_merging_carries_the_open_lists_along(hass: HomeAssistant, seeded: MockConfigEntry):
    """Otherwise the merge is a quiet way to lose a line off today's list."""
    await call(hass, "running_low", {"article": "tomatoes"})

    await call(hass, "merge_articles", {"article": "tomatoes", "into": "minced beef"})

    item = seeded.runtime_data.store.open_items(ListName.SHOPPING)[0]
    assert (item.summary, item.article) == ("minced beef", "minced beef")


async def test_an_article_cannot_be_merged_into_itself(hass: HomeAssistant, seeded: MockConfigEntry):
    """A slip of the finger that would otherwise silently do nothing at all."""
    with pytest.raises(ServiceValidationError):
        await call(hass, "merge_articles", {"article": "rice", "into": "rice"})


async def test_a_removed_article_comes_back_into_its_dishes(hass: HomeAssistant, seeded: MockConfigEntry):
    """Restoring has to mean restoring, or the bin is only half a promise."""
    result = await call(hass, "remove_article", {"article": "minced beef"})
    assert result["from_dishes"] == ["tacos"]
    assert seeded.runtime_data.store.article("minced beef") is None

    await call(hass, "restore_deleted", {"name": "minced beef"})

    store = seeded.runtime_data.store
    assert store.article("minced beef").times == 13
    ingredient = next(i for i in store.dish("tacos").ingredients if i.article == "minced beef")
    assert str(ingredient.certainty) == "certain", "and with what was known about it"


async def test_removing_an_article_never_takes_a_line_off_a_list(hass: HomeAssistant, seeded: MockConfigEntry):
    """A list does not lose a line because of something done in a management screen."""
    await call(hass, "running_low", {"article": "rice"})

    await call(hass, "remove_article", {"article": "rice"})

    assert [i.summary for i in seeded.runtime_data.store.open_items(ListName.SHOPPING)] == ["rice"]


async def test_the_bin_can_be_emptied(hass: HomeAssistant, seeded: MockConfigEntry):
    """A bin nobody can empty is a place things accumulate, not a safety net.

    And something deleted because it should never have been written down has to
    be able to actually go.
    """
    await call(hass, "remove_dish", {"dish": "tacos"})

    await call(hass, "discard_deleted", {"name": "tacos", "kind": "dish"})

    assert (await call(hass, "get_deleted"))["deleted"] == []
    with pytest.raises(ServiceValidationError):
        await call(hass, "restore_deleted", {"name": "tacos", "kind": "dish"})


async def test_restoring_something_that_is_not_in_the_bin_says_so(hass: HomeAssistant, seeded: MockConfigEntry):
    """Silence would look exactly like a restore that worked."""
    with pytest.raises(ServiceValidationError):
        await call(hass, "restore_deleted", {"name": "hyacinth"})


# ---------------------------------------------------------------- departments


async def test_a_department_can_be_added_into_the_walking_route(hass: HomeAssistant, seeded: MockConfigEntry):
    """The order of the departments is the route, so a new one has to be able to land in it."""
    await call(
        hass,
        "set_department",
        {"department": "cheese_counter", "labels": {"en": "Cheese counter"}, "kind": "fresh", "position": 1},
    )

    store = seeded.runtime_data.store
    assert store.department_keys[1] == "cheese_counter", "second in the route, not last"
    row = next(d for d in (await call(hass, "list_departments"))["departments"] if d["key"] == "cheese_counter")
    assert (row["kind"], row["label"], row["articles"]) == ("fresh", "Cheese counter", 0)


async def test_removing_a_department_says_where_its_articles_go(hass: HomeAssistant, seeded: MockConfigEntry):
    """Thirty articles in a department is thirty articles that end up somewhere.

    The only wrong answer is the one nobody was asked, so it is a parameter and
    not a guess.
    """
    await call(hass, "running_low", {"article": "rice"})

    result = await call(hass, "remove_department", {"department": "dry_goods", "move_to": "produce"})

    store = seeded.runtime_data.store
    assert sorted(result["articles"]) == ["poultry rub", "rice"]
    assert store.article("rice").department == "produce"
    assert store.open_items(ListName.SHOPPING)[0].department == "produce"
    assert "dry_goods" not in store.department_keys
    assert "dry_goods" not in store.store_order("Corner Market"), "and out of every walking route"


async def test_removing_a_department_without_saying_where_leaves_them_unfiled(
    hass: HomeAssistant, seeded: MockConfigEntry
):
    """Unclassified is a normal state — it is the bottom of the list, not an error."""
    await call(hass, "remove_department", {"department": "dry_goods"})

    assert seeded.runtime_data.store.article("rice").department == "unknown"


async def test_a_department_that_does_not_exist_cannot_be_removed(hass: HomeAssistant, seeded: MockConfigEntry):
    """Including the one you were going to move the articles into."""
    with pytest.raises(ServiceValidationError):
        await call(hass, "remove_department", {"department": "dry_goods", "move_to": "aisle_seven"})


async def test_a_shop_can_be_added_and_taken_away(hass: HomeAssistant, seeded: MockConfigEntry):
    """A new shop starts from the route as it stands. Correct it in the aisle from there."""
    result = await call(hass, "set_store", {"name": "Big Barn"})
    assert result["department_order"] == seeded.runtime_data.store.department_keys

    await call(hass, "remove_store", {"name": "Big Barn"})
    assert "Big Barn" not in seeded.runtime_data.store.data.stores


# -------------------------------------------------------------------- reading


async def test_the_articles_come_back_alphabetically(hass: HomeAssistant, seeded: MockConfigEntry):
    """This is a screen you arrive at knowing the name of what you want to change.

    The other half of the rule the round cards follow: there you grab, so what
    you used last is on top; here you look up, so it is alphabetical.
    """
    result = await call(hass, "list_articles")

    assert names_in(result) == ["minced beef", "poultry rub", "rice", "tomatoes"]
    assert result["total"] == 4


async def test_the_articles_can_be_searched(hass: HomeAssistant, seeded: MockConfigEntry):
    """A few hundred articles is a scroll nobody finishes."""
    result = await call(hass, "list_articles", {"search": "ri"})

    assert names_in(result) == ["rice"]
    assert result["total"] == 4, "the total is of everything, so the screen can say so"


async def test_an_article_row_says_what_it_belongs_to(hass: HomeAssistant, seeded: MockConfigEntry):
    """Merging two articles safely means seeing which dishes each of them feeds."""
    row = next(a for a in (await call(hass, "list_articles"))["articles"] if a["article"] == "minced beef")

    assert row["dishes"] == ["tacos"]
    assert row["label"] == "Butcher"
    assert row["times"] == 13


async def test_the_departments_come_back_in_walking_order_with_their_weight(
    hass: HomeAssistant, seeded: MockConfigEntry
):
    """Walking order, because this list is the route. The count makes "remove it" answerable.

    The three the shop knows come first, in its order; the departments it has
    never been asked about follow, so nothing is ever missing from the screen
    you would use to file something.
    """
    result = await call(hass, "list_departments")

    assert [d["key"] for d in result["departments"]][:3] == ["produce", "butcher", "dry_goods"]
    assert len(result["departments"]) == len(seeded.runtime_data.store.department_keys)
    assert next(d for d in result["departments"] if d["key"] == "dry_goods")["articles"] == 2
    assert [s["store"] for s in result["stores"]] == ["Corner Market"]


# ------------------------------------------------------------------- history


async def test_a_stretch_of_history_can_be_forgotten(hass: HomeAssistant, seeded: MockConfigEntry, freezer):
    """Blunt on purpose: it exists for rows made by something that was not the household.

    The acceptance run writes seventy-odd real events into the real log every
    evening it is run — true of a test and of nothing else.
    """
    freezer.move_to("2026-08-04 12:00:00+02:00")
    await call(hass, "running_low", {"article": "rice"})
    freezer.move_to("2026-08-06 18:00:00+02:00")
    await call(hass, "running_low", {"article": "tomatoes"})

    result = await call(hass, "forget_events", {"since": "2026-08-04", "until": "2026-08-04"})

    assert result["forgotten"] == 1
    assert [e["article"] for e in (await call(hass, "get_history"))["events"]] == ["tomatoes"]


async def test_forgetting_can_be_narrowed_to_one_kind(hass: HomeAssistant, seeded: MockConfigEntry):
    """Undoing a run of test purchases without losing what really went on a list."""
    await call(hass, "running_low", {"article": "rice"})
    await call(hass, "complete_all")

    result = await call(hass, "forget_events", {"since": "2026-08-06", "until": "2026-08-06", "kind": "bought"})

    assert result["forgotten"] == 1
    assert [e["kind"] for e in (await call(hass, "get_history"))["events"]] == ["listed"]


async def test_the_bin_survives_a_restart(hass: HomeAssistant, seeded: MockConfigEntry):
    """A bin that empties itself when Home Assistant restarts is not a bin."""
    await call(hass, "remove_dish", {"dish": "tacos"})
    store = seeded.runtime_data.store

    revived = type(store)._deserialise(store.serialise())  # noqa: SLF001 - the round trip is the point

    assert [entry.name for entry in revived.deleted] == ["tacos"]
    assert revived.deleted[0].payload["times"] == 18
