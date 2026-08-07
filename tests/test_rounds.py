"""Walking a round, and being able to walk it again.

A round used to be a card that hid a row: "still enough" meant the line went
away until the next redraw, and the day after it was back asking the same
question. That is forgetting, not answering. Here an answer is written down and
counts for as much as buying the thing — and, because people mis-tap, the whole
round can be taken back.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import DOMAIN, EventKind, ListName, Round

TODAY = date(2026, 8, 6)


@pytest.fixture(autouse=True)
def _freeze(freezer):
    freezer.move_to("2026-08-06 18:00:00+02:00")


async def call(hass: HomeAssistant, service: str, data: dict[str, Any] | None = None) -> Any:
    return await hass.services.async_call(DOMAIN, service, data or {}, blocking=True, return_response=True)


@pytest.fixture
async def seeded(hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]) -> MockConfigEntry:
    """A meal plan whose cupboard round has exactly one thing in it: rice."""
    await call(hass, "import_knowledge", {"knowledge": knowledge})
    return entry


def kinds_of(store, article: str) -> list[str]:
    return [event.kind for event in store.data.events if event.article == article]


def articles_in(round_result: dict[str, Any]) -> list[str]:
    return [entry["article"] for entry in round_result["articles"]]


# ------------------------------------------------------------------- answering


async def test_still_enough_is_an_answer_and_not_a_dismissal(hass: HomeAssistant, seeded: MockConfigEntry):
    """The whole reason this file exists.

    Standing at the cupboard and seeing there is plenty settles the question as
    firmly as buying a bag does. It has to survive the next reload, or the round
    is asking about something the household already answered.
    """
    assert articles_in(await call(hass, "get_pantry_check")) == ["rice"]

    await call(hass, "check_off", {"articles": ["rice"]})

    assert articles_in(await call(hass, "get_pantry_check")) == []
    assert articles_in(await call(hass, "get_pantry_check")) == [], "and still gone on a second look"


async def test_the_answer_says_which_round_and_what_it_was(hass: HomeAssistant, seeded: MockConfigEntry):
    """A bare 'checked' cannot be undone selectively or read back usefully."""
    await call(hass, "check_off", {"articles": ["rice"]})

    checked = next(event for event in seeded.runtime_data.store.data.events if event.kind == EventKind.CHECKED)
    assert checked.article == "rice"
    assert checked.on == TODAY
    assert checked.detail == {"round": "pantry", "enough": True}


async def test_running_out_lists_it_in_the_same_gesture(hass: HomeAssistant, seeded: MockConfigEntry):
    """Saying it is gone is not a note about the cupboard but a decision about the shop.

    Splitting the answer from its consequence is what let one happen without the
    other — the row disappeared and nothing was on the list.
    """
    result = await call(hass, "check_off", {"articles": ["rice"], "enough": False})

    assert result["listed"] == ["rice"]
    store = seeded.runtime_data.store
    assert [item.summary for item in store.open_items(ListName.SHOPPING)] == ["rice"]
    assert kinds_of(store, "rice") == [EventKind.CHECKED, EventKind.LISTED]


async def test_running_out_can_go_to_the_next_trip_instead(hass: HomeAssistant, seeded: MockConfigEntry):
    """The way back from a tap on "gone", without leaving the round."""
    await call(hass, "check_off", {"articles": ["rice"], "enough": False, "when": "later"})

    store = seeded.runtime_data.store
    assert store.open_items(ListName.SHOPPING) == []
    assert [item.summary for item in store.open_items(ListName.LATER)] == ["rice"]


async def test_the_whole_round_can_be_answered_at_once(hass: HomeAssistant, seeded: MockConfigEntry):
    """Seeing at a glance that the cupboard is full should not cost twenty taps."""
    await call(hass, "learn_article", {"article": "coffee", "department": "dry_goods", "staple": True})
    assert sorted(articles_in(await call(hass, "get_pantry_check"))) == ["coffee", "rice"]

    result = await call(hass, "check_off")

    assert sorted(result["checked"]) == ["coffee", "rice"]
    assert articles_in(await call(hass, "get_pantry_check")) == []


async def test_only_still_enough_may_answer_a_round_blind(hass: HomeAssistant, seeded: MockConfigEntry):
    """One tap must not be able to put a cupboard's worth of articles on the list."""
    with pytest.raises(ServiceValidationError):
        await call(hass, "check_off", {"enough": False})


# ------------------------------------------------------------------- starting again


async def test_starting_again_puts_todays_answers_back(hass: HomeAssistant, seeded: MockConfigEntry):
    """For a mis-tapped row, or a round somebody else started and left half done."""
    await call(hass, "check_off", {"articles": ["rice"]})
    assert articles_in(await call(hass, "get_pantry_check")) == []

    result = await call(hass, "reset_round")

    assert result["withdrawn"] == 1
    assert articles_in(await call(hass, "get_pantry_check")) == ["rice"]
    assert seeded.runtime_data.store.last_checked("rice") is None


async def test_starting_again_leaves_what_the_answers_caused(hass: HomeAssistant, seeded: MockConfigEntry):
    """Withdrawing an answer is not undoing a purchase.

    Putting something on the list was a separate act, and taking it off is one
    too — a quiet reach into the shopping list because an answer was withdrawn
    is exactly the kind of thing this design does not do. The round stays quiet
    about it either way: being on the list answers the question just as much as
    the withdrawn "gone" did.
    """
    await call(hass, "check_off", {"articles": ["rice"], "enough": False})

    await call(hass, "reset_round")

    store = seeded.runtime_data.store
    assert [item.summary for item in store.open_items(ListName.SHOPPING)] == ["rice"]
    assert store.last_checked("rice") is None, "the answer is withdrawn"
    assert articles_in(await call(hass, "get_pantry_check")) == [], "but the listing answers it too"


async def test_starting_again_does_not_reach_into_yesterday(hass: HomeAssistant, seeded: MockConfigEntry, freezer):
    """Yesterday's cupboard round is history. This button is not an eraser."""
    freezer.move_to("2026-08-05 18:00:00+02:00")
    await call(hass, "check_off", {"articles": ["rice"]})
    freezer.move_to("2026-08-06 18:00:00+02:00")

    assert (await call(hass, "reset_round"))["withdrawn"] == 0
    assert seeded.runtime_data.store.last_checked("rice") == date(2026, 8, 5)


async def test_starting_again_does_not_reach_into_the_other_round(hass: HomeAssistant, seeded: MockConfigEntry):
    """Two rounds, answered on the same evening, taken back one at a time."""
    await call(hass, "add_stock", {"article": "minced beef", "expiry": "2026-08-08"})
    await call(hass, "check_off", {"articles": ["rice"]})
    await call(hass, "check_off", {"articles": ["minced beef"], "round": "fridge"})

    await call(hass, "reset_round", {"round": "fridge"})

    assert seeded.runtime_data.store.last_checked("rice") == TODAY
    assert seeded.runtime_data.store.last_checked("minced beef") is None


# ------------------------------------------------------------------- the fridge


async def test_the_fridge_round_ticks_something_out_of_the_house(hass: HomeAssistant, seeded: MockConfigEntry):
    """Here "gone" means used up, not "buy more" — the same word, the other end."""
    await call(hass, "add_stock", {"article": "minced beef", "expiry": "2026-08-08"})

    result = await call(hass, "check_off", {"articles": ["minced beef"], "enough": False, "round": "fridge"})

    store = seeded.runtime_data.store
    assert result["used"] == ["minced beef"]
    assert result["listed"] == [], "nothing gets bought by emptying the fridge"
    assert store.open_items(ListName.STOCK) == []
    assert EventKind.USED in kinds_of(store, "minced beef")


async def test_the_fridge_round_answered_whole_means_the_dates_still_hold(hass: HomeAssistant, seeded: MockConfigEntry):
    """Same rhythm as the cupboard round, different content: nothing is used up."""
    await call(hass, "add_stock", {"article": "minced beef", "expiry": "2026-08-08"})
    await call(hass, "add_stock", {"article": "tomatoes", "expiry": "2026-08-09"})

    result = await call(hass, "check_off", {"round": "fridge"})

    assert sorted(result["checked"]) == ["minced beef", "tomatoes"]
    assert len(seeded.runtime_data.store.open_items(ListName.STOCK)) == 2


# ------------------------------------------------------------------- moving


async def test_moving_between_lists_is_not_a_new_listing(hass: HomeAssistant, seeded: MockConfigEntry):
    """Otherwise every change of mind about which trip inflates the cadence."""
    await call(hass, "running_low", {"article": "rice", "when": "later"})
    store = seeded.runtime_data.store
    before = store.article("rice").times
    added_on = store.open_items(ListName.LATER)[0].added_on

    result = await call(hass, "move_item", {"item": "rice", "to": "shopping"})

    assert result["moved"] is True
    assert store.open_items(ListName.LATER) == []
    moved = store.open_items(ListName.SHOPPING)[0]
    assert moved.summary == "rice"
    assert moved.added_on == added_on, "the day it was first written down does not change"
    assert store.article("rice").times == before
    assert kinds_of(store, "rice").count(EventKind.LISTED) == 1


async def test_moving_something_that_is_not_on_any_list_says_so(hass: HomeAssistant, seeded: MockConfigEntry):
    """Silence here would look exactly like a move that worked."""
    with pytest.raises(ServiceValidationError):
        await call(hass, "move_item", {"item": "hyacinth", "to": "shopping"})


# ------------------------------------------------------------------- ordering


async def test_the_cupboard_round_leads_with_what_matters_most(hass: HomeAssistant, seeded: MockConfigEntry):
    """Being in this round already means it is urgent, so urgency cannot sort it.

    What is left to say is which of them matters to this household: the thing
    bought most often first, and on a tie the one nobody has looked at for
    longest. Stable enough to remember from one round to the next, which
    alphabetical order never is once an article is added.
    """
    store = seeded.runtime_data.store
    for name, times in (("coffee", 30), ("cat food", 30), ("baking soda", 2)):
        await call(hass, "learn_article", {"article": name, "department": "dry_goods", "staple": True})
        store.article(name).times = times
    # Coffee was looked at in January; cat food never has been.
    store.record_event(EventKind.CHECKED, date(2026, 1, 1), article="coffee", round="pantry", enough=True)

    order = articles_in(await call(hass, "get_pantry_check"))

    assert order[:2] == ["cat food", "coffee"], "same count, so the one longest unlooked-at leads"
    assert order[-1] == "baking soda", "bought twice ever, so it waits"


async def test_the_shop_rides_along_with_the_purchase(hass: HomeAssistant, seeded: MockConfigEntry):
    """The only trace a shop leaves, and what puts it at the front of the chips.

    Nothing else records which shop was used: picking one is a setting, standing
    in one and paying is a fact.
    """
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.meal_plan_store", "option": "Corner Market"}, blocking=True
    )
    await call(hass, "running_low", {"article": "rice"})
    await call(hass, "complete_all")

    bought = next(event for event in seeded.runtime_data.store.data.events if event.kind == EventKind.BOUGHT)
    assert bought.detail["store"] == "Corner Market"
    assert seeded.runtime_data.store.last_shopped("Corner Market") == TODAY


async def test_the_shops_you_use_come_before_the_ones_you_do_not(hass: HomeAssistant, seeded: MockConfigEntry):
    """A row you grab from at the door of a shop, not one you look a name up in."""
    await call(hass, "set_store_order", {"departments": ["dry_goods"], "store": "Big Barn"})
    assert hass.states.get("select.meal_plan_store").attributes["options"] == ["Big Barn", "Corner Market"]

    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.meal_plan_store", "option": "Corner Market"}, blocking=True
    )
    await call(hass, "running_low", {"article": "rice"})
    await call(hass, "complete_all")
    await hass.async_block_till_done()

    assert hass.states.get("select.meal_plan_store").attributes["options"] == ["Corner Market", "Big Barn"]


# ------------------------------------------------------------------- the buttons


async def test_the_card_can_tell_whether_there_is_anything_to_take_back(hass: HomeAssistant, seeded: MockConfigEntry):
    """A "start again" that is always there is a button that usually does nothing."""
    assert hass.states.get("sensor.meal_plan_summary").attributes["checked_today"] == {"pantry": 0, "fridge": 0}

    await call(hass, "check_off", {"articles": ["rice"]})
    await hass.async_block_till_done()

    assert hass.states.get("sensor.meal_plan_summary").attributes["checked_today"] == {"pantry": 1, "fridge": 0}


async def test_the_round_says_when_it_was_last_looked_at(hass: HomeAssistant, seeded: MockConfigEntry, freezer):
    """Saying "due" is an assertion you cannot check; adding a date makes it one you can."""
    freezer.move_to("2026-07-01 18:00:00+02:00")
    await call(hass, "check_off", {"articles": ["rice"]})
    freezer.move_to("2026-08-06 18:00:00+02:00")

    row = (await call(hass, "get_pantry_check"))["articles"][0]

    assert row["article"] == "rice"
    assert row["last_checked"] == "2026-07-01"
    assert row["last_listed"] == "2026-06-01", "both are shown; the card picks the later one"


async def test_a_round_answered_pushes_the_next_one_out_by_the_cadence(
    hass: HomeAssistant, seeded: MockConfigEntry, freezer
):
    """How long does an article go quiet for? Until its own rhythm asks again.

    No new number to invent: the same clock that buying it would have reset.
    """
    freezer.move_to("2026-07-01 18:00:00+02:00")
    await call(hass, "check_off", {"articles": ["rice"]})

    freezer.move_to("2026-08-01 18:00:00+02:00")
    assert articles_in(await call(hass, "get_pantry_check")) == [], "rice runs on a 35 day cadence"

    freezer.move_to("2026-08-10 18:00:00+02:00")
    assert articles_in(await call(hass, "get_pantry_check")) == ["rice"]


def test_every_round_has_a_name_the_card_can_send() -> None:
    """The card sends its own mode straight through as the round."""
    assert {str(round_name) for round_name in Round} == {"pantry", "fridge"}
