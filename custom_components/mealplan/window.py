# SPDX-License-Identifier: GPL-3.0-or-later
"""The planning window.

Which days the menu screen shows. The defaults match a household that plans on
Thursday evening for the week starting Saturday, but every part of it is an
option — this household has already changed its cycle once, and will again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .const import WEEKDAYS


def weekday_index(weekday: str) -> int:
    """Return the position of a weekday key, Monday first, as `date.weekday()` counts."""
    try:
        return WEEKDAYS.index(weekday)
    except ValueError:
        return 0


def weekday_key(day: date) -> str:
    """Return the weekday key for a date."""
    return WEEKDAYS[day.weekday()]


def previous_weekday(today: date, weekday: str) -> date:
    """Return the most recent occurrence of a weekday, on or before today."""
    delta = (today.weekday() - weekday_index(weekday)) % 7
    return today - timedelta(days=delta)


@dataclass(frozen=True, slots=True)
class MenuWindow:
    """The stretch of days the menu screen covers."""

    start: date
    end: date
    extended: bool = False

    @property
    def days(self) -> list[date]:
        """Return every day in the window."""
        count = (self.end - self.start).days + 1
        return [self.start + timedelta(days=offset) for offset in range(max(count, 0))]


def menu_window(
    today: date,
    week_start: str,
    menu_days: int,
    rollover_day: str,
    end_override: date | None = None,
) -> MenuWindow:
    """Return the window to show today.

    Before the rollover day the window is the one already under way; from the
    rollover day on it is the next one, because that is the evening the menu
    actually gets filled in.

    An override stretches the end date — `+1 day`, `+1 week`, or a date the user
    picked. It never shortens the window below its natural length, and it is
    reported as `extended` so the screen can offer a way back rather than
    silently keeping it.
    """
    current_start = previous_weekday(today, week_start)
    rollover_offset = (weekday_index(rollover_day) - weekday_index(week_start)) % 7
    days_in = (today - current_start).days
    start = current_start + timedelta(days=7) if days_in >= rollover_offset else current_start

    natural_end = start + timedelta(days=max(menu_days, 1) - 1)
    if end_override is not None and end_override > natural_end:
        return MenuWindow(start=start, end=end_override, extended=True)
    return MenuWindow(start=start, end=natural_end)
