"""The planning window."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from custom_components.mealplan.window import menu_window, previous_weekday, weekday_key


def test_weekday_key():
    assert weekday_key(date(2026, 8, 6)) == "thu"
    assert weekday_key(date(2026, 8, 8)) == "sat"


def test_previous_weekday_includes_today():
    thursday = date(2026, 8, 6)
    assert previous_weekday(thursday, "thu") == thursday
    assert previous_weekday(thursday, "sat") == date(2026, 8, 1)


@pytest.mark.parametrize(
    ("today", "expected_start"),
    [
        (date(2026, 8, 1), date(2026, 8, 1)),  # Saturday: the window just started
        (date(2026, 8, 5), date(2026, 8, 1)),  # Wednesday: still the current one
        (date(2026, 8, 6), date(2026, 8, 8)),  # Thursday: rolls over, this is planning night
        (date(2026, 8, 7), date(2026, 8, 8)),  # Friday: still the coming one
    ],
)
def test_rollover_happens_on_thursday(today: date, expected_start: date):
    """From Thursday on, the screen shows the week you are about to plan."""
    window = menu_window(today, "sat", 7, "thu")
    assert window.start == expected_start
    assert window.end == expected_start + timedelta(days=6)
    assert len(window.days) == 7
    assert not window.extended


def test_extension_is_visible_and_never_shortens():
    natural = menu_window(date(2026, 8, 6), "sat", 7, "thu")

    stretched = menu_window(date(2026, 8, 6), "sat", 7, "thu", end_override=natural.end + timedelta(days=7))
    assert stretched.extended
    assert len(stretched.days) == 14

    # An override before the natural end is ignored rather than shrinking the week.
    shrunk = menu_window(date(2026, 8, 6), "sat", 7, "thu", end_override=natural.start)
    assert not shrunk.extended
    assert shrunk.end == natural.end
