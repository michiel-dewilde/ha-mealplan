"""The eleven storyboards, played through the integration.

Each test is one scenario from the design work: who is standing where, holding
what, and what has to happen. If a scenario stops working, this is where it
shows — before it shows on a Thursday evening at the kitchen table.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import DOMAIN, UNKNOWN_DEPARTMENT, ListName, ShelfLife
from custom_components.mealplan.llm import async_get_tools

THURSDAY = date(2026, 8, 6)
SATURDAY = date(2026, 8, 8)


@pytest.fixture(autouse=True)
def _freeze(freezer):
    """Every scenario happens on the same Thursday evening."""
    freezer.move_to("2026-08-06 18:00:00+02:00")


@pytest.fixture
async def seeded(hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]) -> MockConfigEntry:
    """A meal plan seeded from a knowledge file, in a Dutch-speaking household."""
    await hass.config.async_update(language="nl")
    await hass.services.async_call(
        DOMAIN, "import_knowledge", {"knowledge": knowledge}, blocking=True, return_response=True
    )
    await hass.services.async_call(DOMAIN, "sort_list", {"store": "Corner Market"}, blocking=True)
    await hass.async_block_till_done()
    return entry


def store_of(entry: MockConfigEntry):
    """Return the store behind a config entry."""
    return entry.runtime_data.store


async def call(hass: HomeAssistant, service: str, data: dict[str, Any] | None = None) -> Any:
    """Call one of our services and return its response."""
    return await hass.services.async_call(DOMAIN, service, data or {}, blocking=True, return_response=True)


# --------------------------------------------------------------------- 1. fridge


async def test_scenario_1_fridge_round(hass: HomeAssistant, seeded: MockConfigEntry):
    """Standing at the open fridge: three things, one after another, in seconds.

    Mince expires Wednesday, the guacamole is open, there is still cucumber. The
    last one carries no date at all — and it must not vanish on its own.
    """
    store = store_of(seeded)

    await call(hass, "set_expiry", {"article": "minced beef", "expiry": "2026-08-12"})
    await call(hass, "add_stock", {"article": "guacamole", "expiry": "2026-08-09"})
    await call(hass, "add_stock", {"article": "cucumber"})

    stock = store.open_items(ListName.STOCK)
    assert [item.summary for item in stock] == ["minced beef", "guacamole", "cucumber"]

    undated = next(item for item in stock if item.summary == "cucumber")
    assert undated.due is None
    assert undated.added_on == THURSDAY, "an undated item records when it was added"

    # Nothing expires by itself: it is still there a month later.
    expiring = await call(hass, "get_expiring", {"days": 30})
    assert [row["article"] for row in expiring["undated"]] == ["cucumber"]


async def test_scenario_1_only_important_articles_are_asked_about(hass: HomeAssistant, seeded: MockConfigEntry):
    """Cheese keeps for weeks; mince does not. Only the second gets asked about."""
    store = store_of(seeded)
    assert store.article_shelf_life("minced beef") == ShelfLife.IMPORTANT
    assert store.article_shelf_life("tomatoes") == ShelfLife.IGNORE

    summary = hass.states.get("sensor.meal_plan_summary")
    assert summary is not None
    assert summary.attributes["watch_expiry"] == ["minced beef"]


async def test_scenario_1_undated_stock_can_be_switched_off(hass: HomeAssistant, entry: MockConfigEntry):
    """The one open question is a flag, not a design: it can simply be off."""
    hass.config_entries.async_update_entry(entry, options={**entry.options, "undated_stock": False})
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await call(hass, "add_stock", {"article": "cucumber"})


# ---------------------------------------------------------------- 2. the cupboard


async def test_scenario_2_two_destinations(hass: HomeAssistant, seeded: MockConfigEntry):
    """Rice and gravy this trip, toilet paper the next one.

    Two destinations, not one. Handwritten lists have had a separate block for
    the next trip for as long as anyone has kept them.
    """
    store = store_of(seeded)

    await call(hass, "running_low", {"article": "rice"})
    await call(hass, "running_low", {"article": "gravy", "when": "now"})
    await call(hass, "running_low", {"article": "toilet paper", "when": "later"})

    assert [item.summary for item in store.open_items(ListName.SHOPPING)] == ["rice", "gravy"]
    assert [item.summary for item in store.open_items(ListName.LATER)] == ["toilet paper"]


async def test_scenario_2_asking_twice_does_not_duplicate(hass: HomeAssistant, seeded: MockConfigEntry):
    await call(hass, "running_low", {"article": "rice"})
    second = await call(hass, "running_low", {"article": "rice"})
    assert second["added"] is False
    assert len(store_of(seeded).open_items(ListName.SHOPPING)) == 1


# ------------------------------------------------------------ 3. going through it


async def test_scenario_3_free_text_never_asks_a_question(hass: HomeAssistant, seeded: MockConfigEntry):
    """Something for the party — no department, no category, no question."""
    store = store_of(seeded)

    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": "todo.meal_plan_shopping_list", "item": "something for the party"},
        blocking=True,
    )

    item = store.find_by_summary(ListName.SHOPPING, "something for the party")
    assert item is not None
    assert item.department == UNKNOWN_DEPARTMENT


async def test_scenario_3_unknown_sorts_last(hass: HomeAssistant, seeded: MockConfigEntry):
    store = store_of(seeded)
    await call(hass, "running_low", {"article": "flowers"})
    await call(hass, "running_low", {"article": "tomatoes"})
    await call(hass, "sort_list", {"store": "Corner Market"})

    assert [item.summary for item in store.open_items(ListName.SHOPPING)] == ["tomatoes", "flowers"]


async def test_scenario_3_learning_is_only_suggested_on_the_third_time(hass: HomeAssistant, seeded: MockConfigEntry):
    """Over half of everything ever bought was bought once. Asking each time is unusable."""
    store = store_of(seeded)
    for _ in range(2):
        await call(hass, "running_low", {"article": "flowers"})
        store.remove_items(ListName.SHOPPING, [i.uid for i in store.items(ListName.SHOPPING)])
    assert store.learn_suggestions() == []

    await call(hass, "running_low", {"article": "flowers"})
    assert store.learn_suggestions() == ["flowers"]


async def test_scenario_3_one_tap_places_an_article(hass: HomeAssistant, seeded: MockConfigEntry):
    store = store_of(seeded)
    await call(hass, "running_low", {"article": "flowers"})
    await call(hass, "learn_article", {"article": "flowers", "department": "produce"})

    assert store.article("flowers").department == "produce"
    assert store.find_by_summary(ListName.SHOPPING, "flowers").department == "produce"
    assert store.learn_suggestions() == []


# ------------------------------------------------------------- 4. in the shop


async def test_scenario_4_list_reads_as_the_walking_route(hass: HomeAssistant, seeded: MockConfigEntry):
    """Produce, then butcher, then dry goods — the order the shop is laid out in."""
    store = store_of(seeded)
    for article in ("rice", "minced beef", "tomatoes"):
        await call(hass, "running_low", {"article": article})
    await call(hass, "sort_list", {"store": "Corner Market"})

    assert [item.summary for item in store.open_items(ListName.SHOPPING)] == [
        "tomatoes",
        "minced beef",
        "rice",
    ]


async def test_scenario_4_availability_is_carried_to_the_list(hass: HomeAssistant, seeded: MockConfigEntry):
    """`kippekruiden COL` is not sold here, and the list has to say so."""
    await call(hass, "running_low", {"article": "poultry rub"})
    item = store_of(seeded).find_by_summary(ListName.SHOPPING, "poultry rub")
    assert item.availability == "Big Barn"


async def test_scenario_4_no_expiry_is_asked_at_the_till(hass: HomeAssistant, seeded: MockConfigEntry):
    """Nobody types five dates with a queue behind them.

    Completing an item on the shopping list must not produce a stock item; the
    expiry date is born at home, when the shopping is put away.
    """
    store = store_of(seeded)
    await call(hass, "add_dish", {"dish": "tacos"})
    await call(hass, "complete_all")

    assert store.open_items(ListName.SHOPPING) == []
    assert store.open_items(ListName.STOCK) == [], "completing does not create expiry entries"


# ----------------------------------------------------------------- 5. on paper


async def test_scenario_5_printable_list(hass: HomeAssistant, seeded: MockConfigEntry):
    """One A4, two columns, department headings, a box per item."""
    for article in ("tomatoes", "minced beef", "rice"):
        await call(hass, "running_low", {"article": article})
    await call(hass, "sort_list", {"store": "Corner Market"})

    printed = await call(hass, "print_list")
    html = printed["html"]

    assert "column-count: 2" in html
    assert html.index("Groenten &amp; fruit") < html.index("Beenhouwerij") < html.index("Droge voeding")
    assert html.count("class='box'") == 3
    assert "@media print" in html
    assert printed["url"].endswith(seeded.entry_id)


async def test_scenario_5_everything_except_the_sausages(hass: HomeAssistant, seeded: MockConfigEntry):
    """The sentence people actually say when they walk back in with the bags."""
    store = store_of(seeded)
    for article in ("tomatoes", "minced beef", "sausages"):
        await call(hass, "running_low", {"article": article})

    result = await call(hass, "complete_all", {"except_items": ["sausages"]})

    assert result["kept"] == ["sausages"]
    assert [item.summary for item in store.open_items(ListName.SHOPPING)] == ["sausages"]


# ------------------------------------------------------- 6. the Thursday ritual


async def test_scenario_6_seven_days_with_notes(hass: HomeAssistant, seeded: MockConfigEntry):
    """Saturday to Friday, some days filled, one left open on purpose."""
    await call(hass, "plan_menu", {"date": "2026-08-14", "dish": "tacos"})
    await call(hass, "plan_menu", {"date": "2026-08-10", "dish": "green beans"})
    await call(hass, "plan_menu", {"date": "2026-08-13", "note": "eating later, training"})

    week = await call(hass, "get_week")
    assert week["start"] == SATURDAY.isoformat()
    assert len(week["days"]) == 7

    by_date = {day["date"]: day for day in week["days"]}
    assert by_date["2026-08-14"]["dish"] == "tacos"
    assert by_date["2026-08-13"]["note"] == "eating later, training"
    assert by_date["2026-08-13"]["dish"] is None
    assert by_date["2026-08-12"] == {
        "date": "2026-08-12",
        "weekday": "wed",
        "dish": None,
        "note": None,
        "people": None,
        "calendar": [],
    }, "an empty day is a normal state, not a gap"


async def test_scenario_6_day_note_never_reaches_a_calendar(hass: HomeAssistant, seeded: MockConfigEntry):
    """The note belongs to the plan. Our own calendar publishes the dish, not the note."""
    await call(hass, "plan_menu", {"date": "2026-08-13", "note": "eating later, training"})
    await hass.async_block_till_done()

    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {"start_date_time": "2026-08-13 00:00:00", "end_date_time": "2026-08-14 00:00:00"},
        target={"entity_id": "calendar.meal_plan_meal_plan"},
        blocking=True,
        return_response=True,
    )
    assert events["calendar.meal_plan_meal_plan"]["events"] == []


async def test_scenario_6_one_tap_from_menu_to_list(hass: HomeAssistant, seeded: MockConfigEntry):
    """Fresh ingredients go on; pantry ones are reported so you can check the cupboard."""
    result = await call(hass, "add_dish", {"dish": "tacos"})

    assert result["added"] == ["minced beef"]
    assert result["pantry"] == ["poultry rub"]
    assert [row["article"] for row in result["suggested"]] == ["tomatoes"]
    assert [item.summary for item in store_of(seeded).open_items(ListName.SHOPPING)] == ["minced beef"]


# ------------------------------------------------------- 7. mid-week correction


async def test_scenario_7_planning_never_touches_a_shopped_list(hass: HomeAssistant, seeded: MockConfigEntry):
    """The shopping is done. Planning Thursday's dinner must add nothing."""
    store = store_of(seeded)
    before = len(store.items(ListName.SHOPPING))

    await call(hass, "plan_menu", {"date": "2026-08-13", "dish": "tacos"})

    assert len(store.items(ListName.SHOPPING)) == before


# ------------------------------------------------------------ 8. AI: the week


async def test_scenario_8_suggestions_use_the_usual_weekday(hass: HomeAssistant, seeded: MockConfigEntry):
    """Tacos are a Friday thing; rice is a Tuesday thing."""
    result = await call(hass, "suggest_menu", {"limit": 2})
    by_date = {row["date"]: row for row in result["suggestions"]}

    friday = by_date["2026-08-14"]["candidates"][0]
    assert friday["dish"] == "tacos"
    assert "usual_day" in friday["reasons"]

    tuesday = by_date["2026-08-11"]["candidates"][0]
    assert tuesday["dish"] == "rice"


async def test_scenario_8_the_model_can_read_before_it_writes(hass: HomeAssistant, seeded: MockConfigEntry):
    """Every AI flow starts with reading. These four are the reason why."""
    names = {tool.name for tool in async_get_tools(hass, seeded)}
    assert {"get_week", "list_dishes", "get_pantry_check", "get_expiring"} <= names

    dishes = await call(hass, "list_dishes")
    taco = next(row for row in dishes["dishes"] if row["name"] == "tacos")
    assert taco["fresh"] == ["minced beef", "tomatoes"]
    assert taco["pantry"] == ["poultry rub"]
    assert taco["usual_day"] == "fri"


# --------------------------------------------------------- 9. AI: what to check


async def test_scenario_9_pantry_check_for_the_menu(hass: HomeAssistant, seeded: MockConfigEntry):
    """What to check is exactly the pantry items — the fresh ones you buy anyway."""
    await call(hass, "plan_menu", {"date": "2026-08-14", "dish": "tacos"})

    result = await call(hass, "get_pantry_check", {"scope": "menu"})
    assert [row["article"] for row in result["articles"]] == ["poultry rub"]


async def test_scenario_9_pantry_check_by_cadence(hass: HomeAssistant, seeded: MockConfigEntry):
    """Rice comes round about every five weeks; six weeks on, it is due."""
    store = store_of(seeded)
    store.record_listing("rice", THURSDAY - timedelta(days=40))

    result = await call(hass, "get_pantry_check", {"scope": "general"})
    assert "rice" in [row["article"] for row in result["articles"]]


# ------------------------------------------------------------- 10. AI: visitors


async def test_scenario_10_people_are_asked_not_inferred(hass: HomeAssistant, seeded: MockConfigEntry):
    """Quantities cannot be derived from the paper, so they are asked for and kept."""
    await call(hass, "plan_menu", {"date": "2026-08-08", "dish": "tacos", "people": 4})
    week = await call(hass, "get_week")
    saturday = next(day for day in week["days"] if day["date"] == "2026-08-08")
    assert saturday["people"] == 4

    result = await call(hass, "add_dish", {"dish": "tacos", "servings": 2})
    item = store_of(seeded).find_by_summary(ListName.SHOPPING, "minced beef")
    assert item.note == "×2", "the multiplier is noted, not calculated"
    assert result["added"] == ["minced beef"]


# ------------------------------------------------ 11. AI: cook what is in the house


async def test_scenario_11_from_stock_to_dish(hass: HomeAssistant, seeded: MockConfigEntry):
    """There is mince that expires Sunday, so which dishes use mince.

    This is the reversal that makes expiry dates worth keeping: a lookup instead
    of a guess.
    """
    await call(hass, "set_expiry", {"article": "minced beef", "expiry": "2026-08-09"})

    # "What can we eat tomorrow?" — one day, not a week.
    tomorrow = (THURSDAY + timedelta(days=1)).isoformat()
    result = await call(hass, "suggest_menu", {"start": tomorrow, "days": 1, "limit": 3})

    day = result["suggestions"][0]
    assert day["date"] == tomorrow
    top = day["candidates"][0]

    assert top["dish"] == "tacos"
    reason = next(r for r in top["reasons"] if r.startswith("expiring:"))
    assert "minced beef" in reason
