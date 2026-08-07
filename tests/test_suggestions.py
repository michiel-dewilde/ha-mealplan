"""How a dish gets suggested, and how it stops being suggested.

Ranking is the part of this integration that is easiest to get subtly, silently
wrong: it always returns something, and the something always looks plausible.
These tests pin the three rules that keep it honest — an interval has to be
earned, a dish that fell out of the rotation stops being offered, and variety is
asked as its own question rather than falling out of the arithmetic.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mealplan.const import DOMAIN
from custom_components.mealplan.store import DORMANT_AFTER_DAYS, MIN_DISH_OBSERVATIONS

TODAY = date(2026, 8, 6)


@pytest.fixture(autouse=True)
def _freeze(freezer):
    freezer.move_to("2026-08-06 18:00:00+02:00")


async def call(hass: HomeAssistant, service: str, data: dict[str, Any] | None = None) -> Any:
    return await hass.services.async_call(DOMAIN, service, data or {}, blocking=True, return_response=True)


def dish(name: str, *, times: int, days_ago: int, interval: float | None, usual_day: str | None = None) -> dict:
    """One dish, described the way a knowledge file describes it."""
    return {
        "name": name,
        "times": times,
        "last": (TODAY - timedelta(days=days_ago)).isoformat(),
        "usual_day": usual_day,
        "interval_days": interval,
        "veggie_variants": 0,
        "recipe_list": None,
        "ingredients": [],
    }


@pytest.fixture
async def rotation(hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]) -> MockConfigEntry:
    """A rotation shaped like a real one: a favourite, a stranger, and a ghost.

    The numbers are the shape that broke it, with invented names. `stranger` was
    eaten twice, six days apart, a year ago — one gap, which is not a rhythm but
    was read as one.

    More dishes than days on purpose. Every day reserves its best fit, so a
    rotation smaller than the window makes every dish somebody's first choice
    and nothing is ever left over to offer as an alternative. Real rotations are
    not like that, and a fixture that is misleads.
    """
    knowledge["dishes"] = [
        dish("favourite", times=36, days_ago=6, interval=10.2, usual_day="fri"),
        dish("weekly", times=26, days_ago=11, interval=14.2, usual_day="tue"),
        dish("regular", times=22, days_ago=35, interval=15.9, usual_day="mon"),
        dish("sunday roast", times=16, days_ago=38, interval=17.9, usual_day="sun"),
        dish("midweek", times=16, days_ago=63, interval=20.1, usual_day="thu"),
        dish("occasional", times=12, days_ago=18, interval=26.0),
        dish("rarity", times=8, days_ago=12, interval=26.9),
        dish("stranger", times=2, days_ago=341, interval=6.0),
        dish("once", times=1, days_ago=200, interval=None),
        dish("ghost", times=3, days_ago=DORMANT_AFTER_DAYS + 40, interval=None),
    ]
    await call(hass, "import_knowledge", {"knowledge": knowledge})
    return entry


async def test_one_gap_is_not_a_rhythm(hass: HomeAssistant, rotation: MockConfigEntry):
    """The bug this file exists for.

    A dish eaten twice, six days apart, a year ago claims "every six days" and
    is thereafter 57 times overdue — worth the maximum overdue bonus, every
    day, forever. That is how a stranger came to outrank a dish eaten 36 times.
    """
    store = rotation.runtime_data.store
    assert store.dish("stranger").interval_days == 6.0, "the file still says so"
    assert store.dish_rhythm("stranger") is None, "but it is not believed"
    assert store.dish_rhythm("favourite") == 10.2, "while a real rhythm is"

    # Each day reserves its best fit, so a dish can be absent from one day's
    # list simply because it was claimed elsewhere. Compare the scores rather
    # than the positions.
    result = await call(hass, "suggest_menu", {"limit": 9})
    best: dict[str, float] = {}
    for day in result["suggestions"]:
        for row in day["candidates"]:
            best[row["dish"]] = max(best.get(row["dish"], 0), row["score"])

    assert best["favourite"] > best["stranger"], f"favourite {best['favourite']} vs stranger {best['stranger']}"
    assert not any(
        "overdue" in row["reasons"]
        for day in result["suggestions"]
        for row in day["candidates"]
        if row["dish"] == "stranger"
    )


async def test_a_rhythm_still_counts_once_it_is_earned(hass: HomeAssistant, rotation: MockConfigEntry):
    """Suppressing a coincidence must not suppress the signal itself."""
    store = rotation.runtime_data.store
    assert store.dish_times("weekly") >= MIN_DISH_OBSERVATIONS

    result = await call(hass, "suggest_menu", {"limit": 5})
    tuesday = next(row for row in result["suggestions"] if row["weekday"] == "tue")
    assert tuesday["candidates"][0]["dish"] == "weekly"
    assert "usual_day" in tuesday["candidates"][0]["reasons"]


async def test_a_dormant_dish_is_not_suggested(hass: HomeAssistant, rotation: MockConfigEntry):
    """Eighteen months without being eaten is out of the rotation."""
    store = rotation.runtime_data.store
    assert store.dish_dormant("ghost", TODAY) is True
    assert store.dish_dormant("stranger", TODAY) is False, "eleven months is not dormant"

    result = await call(hass, "suggest_menu", {"limit": 10})
    everywhere = {row["dish"] for day in result["suggestions"] for row in day["candidates"]}
    assert "ghost" not in everywhere
    assert result["wildcard"] is None or result["wildcard"]["dish"] != "ghost"


async def test_dormant_is_not_deleted(hass: HomeAssistant, rotation: MockConfigEntry):
    """It stops being offered; it does not stop existing.

    Nothing disappears unnoticed — the same rule the lists already live by.
    """
    store = rotation.runtime_data.store
    assert store.dish("ghost") is not None
    assert "ghost" in [row["name"] for row in (await call(hass, "list_dishes"))["dishes"]]

    await call(hass, "plan_menu", {"date": "2026-08-08", "dish": "ghost"})
    assert store.dish_dormant("ghost", TODAY + timedelta(days=2)) is False, "eating it wakes it up"


async def test_variety_is_asked_as_its_own_question(hass: HomeAssistant, rotation: MockConfigEntry):
    """A dish eaten once has no interval, scores nothing, and was never offered.

    Meanwhile a dish with a bogus interval was offered every day. Both are the
    ranking failing at variety, which is why variety gets its own field instead
    of being squeezed into the same number.
    """
    result = await call(hass, "suggest_menu", {"limit": 3})
    wildcard = result["wildcard"]

    assert wildcard is not None
    assert wildcard["dish"] == "stranger", "the one it has been longest since, so the list works through"
    assert wildcard["days_since"] == 341

    top_picks = {day["candidates"][0]["dish"] for day in result["suggestions"] if day["candidates"]}
    assert wildcard["dish"] not in top_picks, "it is an alternative, not a repeat"

    store = rotation.runtime_data.store
    assert store.dish_dormant(wildcard["dish"], TODAY) is False, "and it is not one that fell out of the rotation"


async def test_no_wildcard_when_nothing_has_been_neglected(
    hass: HomeAssistant, entry: MockConfigEntry, knowledge: dict[str, Any]
):
    """Offering "you have not had this in a while" about last week is noise."""
    knowledge["dishes"] = [
        dish("favourite", times=36, days_ago=6, interval=10.2),
        dish("weekly", times=26, days_ago=11, interval=14.2),
    ]
    await call(hass, "import_knowledge", {"knowledge": knowledge})

    result = await call(hass, "suggest_menu", {"limit": 3})
    assert result["wildcard"] is None
