# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent state.

Knowledge is state, not configuration: it is meant to change while the
integration runs, and it belongs in the Home Assistant backup rather than in
`configuration.yaml`.

The store starts with the thirteen default departments and nothing else. That is
a working integration, not a broken one — seeding from a knowledge file is an
accelerator, never a prerequisite.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
import logging
from statistics import mean
from typing import Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_PANTRY_CADENCE_DAYS,
    LEARN_SUGGESTION_THRESHOLD,
    STORAGE_KEY,
    STORAGE_VERSION,
    UNKNOWN_DEPARTMENT,
    DepartmentSource,
    EventKind,
    Kind,
    ListName,
    ShelfLife,
)
from .defaults import DEFAULT_DEPARTMENTS
from .models import Article, DayPlan, Department, Dish, Event, Listing, ListItem, StoreOrder

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 5

MIN_LIVE_LISTINGS = 3
"""Below this, the seeded cadence is the better estimate than what we have measured."""

MIN_DISH_OBSERVATIONS = 4
"""Four meals is three gaps to average. One gap is a coincidence, not a rhythm."""

DORMANT_AFTER_DAYS = 548
"""Eighteen months. Long enough for a yearly dish to come round once and keep itself alive."""

UNKNOWN_LABELS = {"en": "Anything else", "nl": "Nog iets"}
"""What to call the bucket unclassified items land in. Not an error message."""


def _parse_date(value: Any) -> date | None:
    """Parse an ISO date from storage, tolerating null and rubbish."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass(slots=True)
class MealPlanData:
    """Everything the integration knows, in memory."""

    departments: list[Department] = field(default_factory=list)
    stores: dict[str, StoreOrder] = field(default_factory=dict)
    articles: dict[str, Article] = field(default_factory=dict)
    dishes: dict[str, Dish] = field(default_factory=dict)
    plan: dict[date, DayPlan] = field(default_factory=dict)
    listings: list[Listing] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    lists: dict[str, list[ListItem]] = field(default_factory=dict)
    window_end: date | None = None
    """A stretched end date for the menu window, or None for its natural length."""

    source: dict[str, Any] = field(default_factory=dict)


class MealPlanStore:
    """Loads, holds and saves the integration's knowledge and plan."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Set up a store scoped to one config entry."""
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")
        self.data = MealPlanData()

    # ----------------------------------------------------------------- loading

    async def async_load(self) -> None:
        """Load from disk, seeding the default departments on first run."""
        raw = await self._store.async_load()
        if raw is None:
            self.data = MealPlanData(departments=[Department.from_dict(d) for d in DEFAULT_DEPARTMENTS])
            self.async_schedule_save()
            return
        self.data = self._deserialise(raw)

    @staticmethod
    def _deserialise(raw: dict[str, Any]) -> MealPlanData:
        """Rebuild the in-memory model from stored JSON."""
        plan: dict[date, DayPlan] = {}
        for iso, day in (raw.get("plan") or {}).items():
            try:
                plan[date.fromisoformat(iso)] = DayPlan.from_dict(day)
            except ValueError:
                _LOGGER.warning("Discarding plan entry with unparseable date %r", iso)

        listings = [Listing.from_dict(item) for item in raw.get("listings") or []]
        events = [Event.from_dict(item) for item in raw.get("events") or []]

        return MealPlanData(
            departments=[Department.from_dict(d) for d in raw.get("departments") or DEFAULT_DEPARTMENTS],
            stores={name: StoreOrder.from_dict(s) for name, s in (raw.get("stores") or {}).items()},
            articles={a["name"]: Article.from_dict(a) for a in raw.get("articles") or []},
            dishes={d["name"]: Dish.from_dict(d) for d in raw.get("dishes") or []},
            plan=plan,
            listings=[item for item in listings if item is not None],
            events=[item for item in events if item is not None],
            lists={name: [ListItem.from_dict(i) for i in items] for name, items in (raw.get("lists") or {}).items()},
            window_end=_parse_date(raw.get("window_end")),
            source=raw.get("source") or {},
        )

    def serialise(self) -> dict[str, Any]:
        """Render the in-memory model as storable JSON."""
        return {
            "departments": [d.to_dict() for d in self.data.departments],
            "stores": {name: s.to_dict() for name, s in self.data.stores.items()},
            "articles": [a.to_dict() for a in self.data.articles.values()],
            "dishes": [d.to_dict() for d in self.data.dishes.values()],
            "plan": {day.isoformat(): entry.to_dict() for day, entry in sorted(self.data.plan.items())},
            "listings": [item.to_dict() for item in self.data.listings],
            "events": [item.to_dict() for item in self.data.events],
            "lists": {name: [i.to_dict() for i in items] for name, items in self.data.lists.items()},
            "window_end": self.data.window_end.isoformat() if self.data.window_end else None,
            "source": self.data.source,
        }

    def async_schedule_save(self) -> None:
        """Queue a debounced save."""
        self._store.async_delay_save(self.serialise, SAVE_DELAY)

    async def async_save_now(self) -> None:
        """Write immediately, for shutdown and for tests."""
        await self._store.async_save(self.serialise())

    # -------------------------------------------------------------- department

    def department(self, key: str) -> Department | None:
        """Return a department by key, or None."""
        return next((d for d in self.data.departments if d.key == key), None)

    @property
    def department_keys(self) -> list[str]:
        """Return every department key, in the stored order."""
        return [d.key for d in self.data.departments]

    def department_label(self, key: str, language: str) -> str:
        """Return the display label for a department key.

        `unknown` is not a department and is deliberately absent from the list,
        but it does become a heading on screen and on paper — where "UNKNOWN"
        reads like a fault rather than the perfectly ordinary "everything else".
        """
        if key == UNKNOWN_DEPARTMENT:
            return UNKNOWN_LABELS.get(language, UNKNOWN_LABELS["en"])
        department = self.department(key)
        return department.label(language) if department else key

    # ------------------------------------------------------------------ stores

    def store_order(self, store: str | None) -> list[str]:
        """Return the department order for a store.

        Falls back to the store's own order first, then to the order the
        departments are stored in — which is the walking route of a typical shop
        and therefore a sane default for a store nobody has configured yet.
        """
        known = self.department_keys
        configured = self.data.stores.get(store or "", StoreOrder()).department_order
        ordered = [key for key in configured if key in known]
        ordered += [key for key in known if key not in ordered]
        return ordered

    def sort_index(self, department: str, store: str | None) -> int:
        """Return the sort position of a department. Unknown always sorts last."""
        if department == UNKNOWN_DEPARTMENT:
            return len(self.data.departments) + 1
        order = self.store_order(store)
        return order.index(department) if department in order else len(order)

    # ---------------------------------------------------------------- articles

    def article(self, name: str) -> Article | None:
        """Return an article by name, or None."""
        return self.data.articles.get(name)

    def ensure_article(self, name: str) -> Article:
        """Return an article, creating an unclassified one if it is new.

        Creating it is deliberately silent. Classification must never block
        putting something on a list — an unknown article lands in `unknown` at
        the bottom and can be placed later, or never.
        """
        existing = self.data.articles.get(name)
        if existing is not None:
            return existing
        article = Article(name=name, department=UNKNOWN_DEPARTMENT, department_source=DepartmentSource.UNKNOWN)
        self.data.articles[name] = article
        return article

    def article_kind(self, name: str) -> Kind | None:
        """Return whether an article is fresh or pantry, deriving it from its department."""
        article = self.article(name)
        if article is None:
            return None
        if article.kind is not None:
            return article.kind
        department = self.department(article.department)
        return department.kind if department else None

    def article_shelf_life(self, name: str) -> ShelfLife:
        """Return how much an article's expiry date matters.

        The department sets the default; the article overrides it. Yoghurt sits
        in `dairy` but spoils fast, parmesan sits there too and keeps for months.
        """
        article = self.article(name)
        if article is None:
            return ShelfLife.IGNORE
        return article.shelf_life

    def record_listing(self, name: str, on: date) -> Article:
        """Record that an article went onto a list, and count it."""
        article = self.ensure_article(name)
        article.times += 1
        self.data.listings.append(Listing(article=name, on=on))
        return article

    # ------------------------------------------------------------------ events

    def record_event(
        self,
        kind: EventKind,
        on: date,
        *,
        article: str | None = None,
        dish: str | None = None,
        **detail: Any,
    ) -> Event:
        """Write down that something happened."""
        event = Event(
            kind=str(kind),
            on=on,
            article=article,
            dish=dish,
            detail={key: value for key, value in detail.items() if value is not None},
        )
        self.data.events.append(event)
        return event

    def last_event(self, kind: EventKind, *, article: str) -> date | None:
        """Return when this article last had an event of this kind."""
        days = [event.on for event in self.data.events if event.kind == kind and event.article == article]
        return max(days) if days else None

    def record_past_meals(self, today: date) -> int:
        """Turn plans that have come and gone into facts.

        A plan is a intention and can be edited or cleared afterwards; what was
        actually on the table on a day that has passed should survive that. So
        once a planned day is behind us it is written down, once, and the plan
        is then free to change without rewriting history.

        Backfilled on every write rather than on a timer: it is a scan over a
        few hundred days, it cannot drift, and there is nothing to schedule.
        """
        already = {event.on for event in self.data.events if event.kind == EventKind.EATEN}
        added = 0
        for day, entry in self.data.plan.items():
            if day < today and entry.dish and day not in already:
                self.record_event(EventKind.EATEN, day, dish=entry.dish, people=entry.people)
                added += 1
        return added

    def last_listed(self, name: str) -> date | None:
        """Return the most recent day this article went onto a list.

        Seeded and live together, most recent wins. Without the seeded date a
        freshly imported knowledge base knows how often something comes round
        but not when it last did, which is the same as not knowing.
        """
        days = [item.on for item in self.data.listings if item.article == name]
        article = self.article(name)
        if article is not None and article.last_listed is not None:
            days.append(article.last_listed)
        return max(days) if days else None

    def cadence_days(self, name: str) -> float | None:
        """Return the average gap between two listings.

        Live measurements win once there are enough of them; before that, the
        seeded cadence is the better estimate. Neither alone is right: seeded
        data ages, and live data starts empty.
        """
        days = sorted({item.on for item in self.data.listings if item.article == name})
        if len(days) >= MIN_LIVE_LISTINGS:
            gaps = [(b - a).days for a, b in pairwise(days)]
            live = mean(g for g in gaps if g > 0) if any(g > 0 for g in gaps) else None
            if live:
                return round(live, 1)
        article = self.article(name)
        return article.cadence_days if article else None

    def recurs(self, name: str) -> bool:
        """Return whether this article is something you buy again.

        Over half of everything ever bought was bought exactly once — a can
        opener, a splatter lid, a whiteboard marker. Those have no cadence, and
        treating "no cadence" as "the default cadence" turns every one of them
        into a standing obligation. Something recurs if it has been seen twice
        (so there is a real gap to measure) or if it is a staple.
        """
        article = self.article(name)
        return self.cadence_days(name) is not None or bool(article and article.staple)

    def is_due(self, name: str, today: date) -> bool:
        """Return whether a recurring pantry article is due by its own cadence."""
        last = self.last_listed(name)
        if last is None or not self.recurs(name):
            return False
        cadence = self.cadence_days(name) or DEFAULT_PANTRY_CADENCE_DAYS
        return (today - last).days >= cadence

    # ------------------------------------------------------------------ dishes

    def dish(self, name: str) -> Dish | None:
        """Return a dish by name, or None."""
        return self.data.dishes.get(name)

    def dish_times(self, name: str) -> int:
        """Return how often a dish was planned, seeded plus live."""
        dish = self.dish(name)
        seeded = dish.times if dish else 0
        return seeded + sum(1 for entry in self.data.plan.values() if entry.dish == name)

    def dish_last(self, name: str, today: date) -> date | None:
        """Return when a dish was last on the table, seeded plus live.

        Days in the future do not count: a dish planned for Friday has not been
        eaten yet, and treating it as such would suppress it from suggestions
        for the wrong reason.
        """
        dish = self.dish(name)
        candidates = [d for d in (dish.last if dish else None,) if d is not None]
        candidates += [day for day, entry in self.data.plan.items() if entry.dish == name and day <= today]
        return max(candidates) if candidates else None

    def dish_rhythm(self, name: str) -> float | None:
        """Return how often a dish comes round, or None if that is not known.

        A stated interval is only believed once the dish has been eaten enough
        times to have a rhythm rather than a coincidence. Below the threshold
        two meals a week apart, once, would claim "every seven days" and stay
        maximally overdue for the rest of the installation's life.

        The same reasoning as `recurs` on the article side: no measurement is
        not the same as a default measurement.
        """
        dish = self.dish(name)
        if dish is None or not dish.interval_days:
            return None
        return dish.interval_days if self.dish_times(name) >= MIN_DISH_OBSERVATIONS else None

    def dish_dormant(self, name: str, today: date) -> bool:
        """Return whether a dish has fallen out of the rotation.

        Eighteen months rather than twelve, and deliberately: a dish eaten every
        January is not retired in July. Twelve months would drop it from the
        suggestions in the last weeks before its season comes round, and it
        would then never resurface on its own.

        Dormant is not deleted. The dish stays in the knowledge base and in the
        type-ahead, and eating it once wakes it up.
        """
        last = self.dish_last(name, today)
        return last is not None and (today - last).days > DORMANT_AFTER_DAYS

    def dish_ingredients(self, name: str, kind: Kind | None = None) -> list[str]:
        """Return a dish's ingredient article names, optionally filtered by kind."""
        dish = self.dish(name)
        if dish is None:
            return []
        if kind is None:
            return [i.article for i in dish.ingredients]
        return [i.article for i in dish.ingredients if self.article_kind(i.article) == kind]

    # -------------------------------------------------------------------- plan

    def day(self, on: date) -> DayPlan:
        """Return the plan for a day, or an empty one. Empty is a normal state."""
        return self.data.plan.get(on, DayPlan())

    def set_day(self, on: date, entry: DayPlan) -> None:
        """Store or clear the plan for a day."""
        if entry.is_empty:
            self.data.plan.pop(on, None)
        else:
            self.data.plan[on] = entry

    def planned_dishes(self, start: date, end: date) -> list[str]:
        """Return the dishes planned between two dates, inclusive, without duplicates."""
        seen: dict[str, None] = {}
        for day, entry in sorted(self.data.plan.items()):
            if start <= day <= end and entry.dish:
                seen.setdefault(entry.dish, None)
        return list(seen)

    def usual_dish_for(self, weekday: str) -> str | None:
        """Return the dish this household usually has on a given weekday."""
        counts: dict[str, int] = defaultdict(int)
        for dish in self.data.dishes.values():
            if dish.usual_day == weekday:
                counts[dish.name] = dish.times
        if not counts:
            return None
        return max(counts, key=lambda name: counts[name])

    # ------------------------------------------------------------------- lists

    def items(self, list_name: ListName | str) -> list[ListItem]:
        """Return the items on a list, creating the list if it does not exist yet."""
        return self.data.lists.setdefault(str(list_name), [])

    def open_items(self, list_name: ListName | str) -> list[ListItem]:
        """Return only the items that still need doing."""
        return [item for item in self.items(list_name) if not item.completed]

    def find_item(self, list_name: ListName | str, uid: str) -> ListItem | None:
        """Return an item by uid, or None."""
        return next((item for item in self.items(list_name) if item.uid == uid), None)

    def find_by_summary(self, list_name: ListName | str, summary: str) -> ListItem | None:
        """Return the first open item whose summary matches, case-insensitively."""
        folded = summary.casefold().strip()
        return next((item for item in self.open_items(list_name) if item.summary.casefold() == folded), None)

    def add_item(
        self,
        list_name: ListName | str,
        summary: str,
        today: date,
        *,
        due: date | None = None,
        note: str | None = None,
        dish: str | None = None,
        article_name: str | None = None,
    ) -> ListItem:
        """Put something on a list.

        The article name is looked up if it is known, and created unclassified if
        it is not. Either way this never asks a question: what the user typed
        goes on the list, and the classification catches up later or not at all.
        """
        name = article_name if article_name is not None else summary.strip()
        article = self.record_listing(name, today)
        self.record_event(
            EventKind.STOCKED if str(list_name) == ListName.STOCK else EventKind.LISTED,
            today,
            article=article.name,
            dish=dish,
            list=str(list_name),
            due=due.isoformat() if due else None,
        )
        item = ListItem(
            uid=uuid.uuid4().hex,
            summary=summary.strip(),
            due=due,
            department=article.department,
            note=note,
            availability=article.availability,
            added_on=today,
            dish=dish,
            article=article.name,
        )
        self.items(list_name).append(item)
        return item

    def complete_item(self, list_name: ListName | str, item: ListItem, today: date) -> None:
        """Tick an item off, and write down what that means for this list.

        Ticking off a shopping item means it was bought — which until now was
        nowhere recorded. Every cadence this integration reasons with was
        measured on "went onto a list" instead, which is a near miss: things get
        written down and then not bought.

        On the stock list the same gesture means the opposite end of the story:
        it has been used up. The expiry date rides along as a fact, without any
        conclusion about whether it was eaten in time.
        """
        if item.completed:
            return
        item.completed = True
        stock = str(list_name) == ListName.STOCK
        self.record_event(
            EventKind.USED if stock else EventKind.BOUGHT,
            today,
            article=item.article or item.summary,
            dish=item.dish,
            list=str(list_name),
            due=item.due.isoformat() if item.due else None,
        )

    def remove_items(self, list_name: ListName | str, uids: Iterable[str], today: date | None = None) -> None:
        """Take items off a list.

        Anything still open when it goes is recorded as `unlisted`: it was
        written down and then did not happen, which is worth being able to tell
        apart from having been bought.
        """
        doomed = set(uids)
        items = self.items(list_name)
        if today is not None:
            for item in items:
                if item.uid in doomed and not item.completed:
                    self.record_event(
                        EventKind.UNLISTED,
                        today,
                        article=item.article or item.summary,
                        list=str(list_name),
                    )
        self.data.lists[str(list_name)] = [item for item in items if item.uid not in doomed]

    def sort_list(self, list_name: ListName | str, store: str | None) -> None:
        """Reorder the open items into the walking route of a store.

        Completed items keep their place at the end. Sorting is stable, so items
        within one department stay in the order they were added — which is the
        order they were thought of, and often the order they sit on the shelf.
        """
        items = self.items(list_name)
        open_items = [item for item in items if not item.completed]
        done = [item for item in items if item.completed]
        open_items.sort(key=lambda item: self.sort_index(item.department, store))
        self.data.lists[str(list_name)] = open_items + done

    def learn_suggestions(self) -> list[str]:
        """Return unclassified articles that have shown up often enough to be worth learning.

        Deliberately a passive list rather than a prompt: over half of all
        articles ever bought were bought exactly once, and asking about each of
        them would make the list unusable.
        """
        return [
            article.name
            for article in self.data.articles.values()
            if article.department == UNKNOWN_DEPARTMENT and article.times >= LEARN_SUGGESTION_THRESHOLD
        ]
