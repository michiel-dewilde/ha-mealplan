# SPDX-License-Identifier: GPL-3.0-or-later
"""What the integration can actually do.

Every service and every LLM tool ends up here. Keeping the behaviour in plain
functions rather than in the service layer is what makes one implementation
serve the dashboard, the MCP server and Assist alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_HISTORY_LIMIT,
    DOMAIN,
    MAX_HISTORY_LIMIT,
    SIGNAL_UPDATED,
    UNKNOWN_DEPARTMENT,
    Certainty,
    DepartmentSource,
    EventKind,
    IngredientSource,
    Kind,
    ListName,
    PantryScope,
    Round,
    ShelfLife,
    StoreSource,
    When,
)
from .models import DayPlan, Dish, Ingredient, StoreOrder
from .options import plan_options
from .store import MealPlanStore
from .types import MealPlanConfigEntry
from .window import menu_window, weekday_key

# How strongly each signal pushes a dish up the suggestion list.
SCORE_EXPIRING = 100.0
SCORE_USUAL_DAY = 50.0
SCORE_OVERDUE = 20.0
SCORE_FREQUENCY = 1.0

DEFAULT_EXPIRY_HORIZON_DAYS = 7
DEFAULT_SUGGESTION_LIMIT = 3

# How long ago a dish has to have been eaten before it is worth offering as
# "we have not had this in a while". Six weeks is roughly the point where a
# household stops thinking of a dish as recent.
WILDCARD_MIN_DAYS = 42


@dataclass(slots=True)
class Context:
    """One configured meal plan, plus today's date."""

    hass: HomeAssistant
    entry: MealPlanConfigEntry
    today: date

    @property
    def store(self) -> MealPlanStore:
        """Return the store."""
        return self.entry.runtime_data.store

    @property
    def language(self) -> str:
        """Return the user interface language."""
        return self.hass.config.language

    @property
    def selected_store(self) -> str | None:
        """Return the store currently selected."""
        return self.entry.runtime_data.store_choice

    def commit(self) -> None:
        """Persist and tell the entities to redraw.

        Also the moment plans that have come and gone become facts. Doing it
        here rather than on a timer means there is nothing to schedule and
        nothing that can drift: any write is an opportunity to catch up.
        """
        self.store.record_past_meals(self.today)
        self.store.async_schedule_save()
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    def window(self) -> Any:
        """Return the current planning window."""
        options = plan_options(self.entry)
        return menu_window(
            self.today,
            options.week_start,
            options.menu_days,
            options.rollover_day,
            self.store.data.window_end,
        )


def context(hass: HomeAssistant, entry: MealPlanConfigEntry) -> Context:
    """Build a context for a config entry."""
    return Context(hass=hass, entry=entry, today=dt_util.now().date())


# --------------------------------------------------------------------- writing


def add_dish(
    ctx: Context,
    dish_name: str,
    *,
    servings: int | None = None,
    include_pantry: bool = False,
) -> dict[str, Any]:
    """Put a dish's fresh ingredients on the shopping list.

    Only the certain ones go on by themselves. Likely and possible ones come
    back as suggestions, and pantry ingredients come back as something to check
    — planning a meal is not a reason to buy rice, running out is.
    """
    store = ctx.store
    dish = store.dish(dish_name)
    if dish is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_dish", translation_placeholders={"dish": dish_name}
        )

    added: list[str] = []
    suggested: list[dict[str, str]] = []
    pantry: list[str] = []
    already: list[str] = []

    note = f"×{servings}" if servings and servings > 1 else None

    for ingredient in dish.ingredients:
        kind = store.article_kind(ingredient.article)
        if kind == Kind.PANTRY:
            pantry.append(ingredient.article)
            if not include_pantry:
                continue
        if store.find_by_summary(ListName.SHOPPING, ingredient.article) is not None:
            already.append(ingredient.article)
            continue
        if ingredient.certainty != Certainty.CERTAIN and kind != Kind.PANTRY:
            suggested.append({"article": ingredient.article, "certainty": str(ingredient.certainty)})
            continue
        store.add_item(ListName.SHOPPING, ingredient.article, ctx.today, note=note, dish=dish_name)
        added.append(ingredient.article)

    store.sort_list(ListName.SHOPPING, ctx.selected_store)
    ctx.commit()
    return {"dish": dish_name, "added": added, "suggested": suggested, "pantry": pantry, "already_listed": already}


def running_low(ctx: Context, article: str, when: When = When.NOW) -> dict[str, Any]:
    """Put one article that is running low on a list.

    Two destinations, because the paper already had two: what has to come along
    this trip, and what can wait for the next one.

    The uid comes back so that whoever asked can undo it without searching for
    what they just added — that is what makes "→ next trip" a single tap
    straight after "gone" rather than a trip to the list.
    """
    list_name = ListName.SHOPPING if when == When.NOW else ListName.LATER
    if (existing := ctx.store.find_by_summary(list_name, article)) is not None:
        return {"article": existing.summary, "uid": existing.uid, "list": str(list_name), "added": False}

    item = ctx.store.add_item(list_name, article, ctx.today)
    ctx.store.sort_list(list_name, ctx.selected_store)
    ctx.commit()
    return {"article": item.summary, "uid": item.uid, "list": str(list_name), "added": True}


def move_item(ctx: Context, item: str, to: ListName, from_list: ListName | None = None) -> dict[str, Any]:
    """Move something from one list to another.

    The item is named by uid or by what it says. Moving is not listing: nothing
    is recorded and the day it was first written down stays as it was. It is the
    same item, on a different list.
    """
    store = ctx.store
    sources = [from_list] if from_list is not None else [name for name in ListName if name != to]

    for source in sources:
        found = store.find_item(source, item) or store.find_by_summary(source, item)
        if found is None:
            continue
        if source == to:
            return {"item": found.summary, "uid": found.uid, "list": str(to), "moved": False}
        store.move_item(found, source, to)
        store.sort_list(to, ctx.selected_store)
        ctx.commit()
        return {"item": found.summary, "uid": found.uid, "from": str(source), "list": str(to), "moved": True}

    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="unknown_item", translation_placeholders={"item": item}
    )


def check_off(
    ctx: Context,
    *,
    articles: list[str] | None = None,
    enough: bool = True,
    round_name: Round = Round.PANTRY,
    scope: PantryScope = PantryScope.GENERAL,
    when: When = When.NOW,
) -> dict[str, Any]:
    """Answer a round: for each article, still enough or run out.

    One service for the whole round, because the round asks one question. Before
    this, "still enough" was a card hiding a row until the next redraw — the
    answer existed for as long as you were looking at it. Now it is written
    down, and `store.last_answer` treats having looked as worth the same as
    having bought: the question is answered until the article's own cadence asks
    again.

    The consequence rides along with the answer rather than being a second act.
    "Gone" at a cupboard puts it on the list; "gone" at the fridge ticks it out
    of the house. That is what the tap means, and splitting the two would let
    one happen without the other.

    Without `articles` this answers the whole round — the "I can see the
    cupboard is full" case. Only for "still enough": answering "gone" for
    everything you did not look at is not something a tap should be able to do
    by accident.
    """
    store = ctx.store
    fridge = round_name == Round.FRIDGE

    if articles is None:
        if not enough:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="check_off_needs_articles")
        if fridge:
            names = [item.summary for item in store.open_items(ListName.STOCK)]
        else:
            # What is already on the list has been answered another way.
            names = [
                entry["article"] for entry in get_pantry_check(ctx, scope)["articles"] if not entry["already_listed"]
            ]
    else:
        names = [name.strip() for name in articles if name.strip()]

    listed: list[str] = []
    used: list[str] = []
    for name in names:
        store.record_event(EventKind.CHECKED, ctx.today, article=name, round=str(round_name), enough=enough)
        if enough:
            continue
        if fridge:
            item = store.find_by_summary(ListName.STOCK, name)
            if item is not None:
                store.complete_item(ListName.STOCK, item, ctx.today)
                used.append(name)
        elif store.find_by_summary(ListName.SHOPPING if when == When.NOW else ListName.LATER, name) is None:
            target = ListName.SHOPPING if when == When.NOW else ListName.LATER
            store.add_item(target, name, ctx.today)
            store.sort_list(target, ctx.selected_store)
            listed.append(name)

    ctx.commit()
    return {
        "round": str(round_name),
        "enough": enough,
        "checked": names,
        "listed": listed,
        "used": used,
        "checked_today": len(store.checks_on(ctx.today, str(round_name))),
    }


def reset_round(ctx: Context, round_name: Round = Round.PANTRY) -> dict[str, Any]:
    """Take back today's answers to a round, so it asks everything again.

    For a mis-tapped row, or a round somebody else started and left half done.
    Only today's: yesterday's cupboard round is history and this is not an
    eraser.

    What the answers *caused* stays. Something you put on the list is on the
    list, and it says so on the row when the round comes back — putting it on
    was a separate act and taking it off is one too. Undoing a purchase because
    an answer was withdrawn is exactly the kind of quiet reach this design does
    not make.
    """
    withdrawn = ctx.store.forget_checks(ctx.today, str(round_name))
    ctx.commit()
    return {"round": str(round_name), "withdrawn": withdrawn, "checked_today": 0}


def plan_menu(
    ctx: Context,
    on: date,
    *,
    dish: str | None = None,
    note: str | None = None,
    people: int | None = None,
    clear: bool = False,
) -> dict[str, Any]:
    """Put a dish on a day.

    Never touches the shopping list. Topping the list up is always a separate,
    visible act — a dish planned on Tuesday for Thursday must not silently add
    things to a list that has already been shopped.
    """
    current = ctx.store.day(on)
    entry = DayPlan(
        dish=None if clear else (dish if dish is not None else current.dish),
        note=None if clear else (note if note is not None else current.note),
        people=None if clear else (people if people is not None else current.people),
    )
    ctx.store.set_day(on, entry)
    ctx.commit()
    return {"date": on.isoformat(), **entry.to_dict()}


def complete_all(ctx: Context, except_items: list[str] | None = None) -> dict[str, Any]:
    """Complete everything on the shopping list, except what is named.

    This is "got everything except the sausages", the sentence people actually
    say when they walk back in with the bags.
    """
    keep = [text.casefold().strip() for text in except_items or [] if text.strip()]
    completed: list[str] = []
    kept: list[str] = []

    for item in ctx.store.open_items(ListName.SHOPPING):
        folded = item.summary.casefold()
        if any(text in folded or folded in text for text in keep):
            kept.append(item.summary)
            continue
        ctx.store.complete_item(ListName.SHOPPING, item, ctx.today, store=ctx.selected_store)
        completed.append(item.summary)

    ctx.commit()
    return {"completed": completed, "kept": kept}


def sort_list(ctx: Context, store_name: str | None = None) -> dict[str, Any]:
    """Reorder the open items into the walking route of a store.

    A store nobody has described yet gets the department order as it stands,
    which is a reasonable supermarket and a starting point to drag around.
    """
    store = ctx.store
    chosen = store_name or ctx.selected_store
    if chosen and chosen not in store.data.stores:
        store.data.stores[chosen] = StoreOrder(
            department_order=store.department_keys, lists=0, source=StoreSource.MANUAL
        )
    for list_name in (ListName.SHOPPING, ListName.LATER):
        store.sort_list(list_name, chosen)
    ctx.commit()
    return {"store": chosen, "order": store.store_order(chosen)}


def set_store_order(ctx: Context, departments: list[str], store_name: str | None = None) -> dict[str, Any]:
    """Record the walking route of a store.

    Written to be used standing in an aisle, not at a desk: the order that is
    wrong is wrong *now*, and waiting until you are home means it never gets
    fixed. So the open list is re-sorted immediately when the store you correct
    is the one you are in.

    Departments left out keep their relative order at the end, which makes
    "move this one up" a complete instruction rather than a full permutation.
    """
    name = store_name or ctx.selected_store
    if not name:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_store")

    known = ctx.store.department_keys
    if unknown := [key for key in departments if key not in known]:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_department",
            translation_placeholders={"department": ", ".join(unknown)},
        )

    order = list(dict.fromkeys(departments))
    order += [key for key in known if key not in order]

    existing = ctx.store.data.stores.get(name, StoreOrder())
    existing.department_order = order
    existing.source = StoreSource.MANUAL
    ctx.store.data.stores[name] = existing

    if name == ctx.selected_store:
        ctx.store.sort_list(ListName.SHOPPING, name)
        ctx.store.sort_list(ListName.LATER, name)
    ctx.commit()
    return {"store": name, "department_order": order}


def set_expiry(ctx: Context, article: str, expiry: date) -> dict[str, Any]:
    """Record when something in the fridge goes off.

    Asked for at home, while putting the shopping away or during a round at the
    fridge — never at the till, where nobody types five dates with a queue
    behind them.
    """
    store = ctx.store
    existing = store.find_by_summary(ListName.STOCK, article)
    if existing is not None:
        existing.due = expiry
        # Adding it and dating it are the same statement — "this is in the
        # house until then" — so they are the same event.
        store.record_event(EventKind.STOCKED, ctx.today, article=existing.article or article, due=expiry.isoformat())
    else:
        store.add_item(ListName.STOCK, article, ctx.today, due=expiry)

    known = store.article(article)
    if known is not None:
        known.expiry_seen = True
    ctx.commit()
    return {"article": article, "expiry": expiry.isoformat()}


def add_stock(ctx: Context, article: str, expiry: date | None = None) -> dict[str, Any]:
    """Note that something is in the house, with or without a date.

    Undated items are allowed only if the option is on, and they never vanish by
    themselves: they sit there, with the day they were added, until someone
    ticks them off. Something that disappears unnoticed costs you trust in the
    whole list.
    """
    if expiry is None and not plan_options(ctx.entry).undated_stock:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="undated_stock_disabled")
    if expiry is not None:
        return set_expiry(ctx, article, expiry)

    if (existing := ctx.store.find_by_summary(ListName.STOCK, article)) is not None:
        return {"article": existing.summary, "expiry": None, "added": False}
    item = ctx.store.add_item(ListName.STOCK, article, ctx.today)
    ctx.commit()
    return {"article": item.summary, "expiry": None, "added": True}


def learn_dish(
    ctx: Context,
    dish_name: str,
    ingredients: list[str],
    *,
    usual_day: str | None = None,
    recipe_list: str | None = None,
) -> dict[str, Any]:
    """Teach it a dish, or add ingredients to one it already knows."""
    store = ctx.store
    dish = store.dish(dish_name)
    if dish is None:
        dish = Dish(name=dish_name)
        store.data.dishes[dish_name] = dish

    known = {ingredient.article for ingredient in dish.ingredients}
    for name in ingredients:
        clean = name.strip()
        if not clean or clean in known:
            continue
        article = store.ensure_article(clean)
        dish.ingredients.append(
            Ingredient(
                article=clean,
                certainty=Certainty.CERTAIN,
                source=IngredientSource.MANUAL,
                department=article.department,
            )
        )
        known.add(clean)

    if usual_day:
        dish.usual_day = usual_day
    if recipe_list:
        dish.recipe_list = recipe_list

    ctx.commit()
    return {"dish": dish.name, "ingredients": [i.article for i in dish.ingredients]}


def learn_article(
    ctx: Context,
    article: str,
    department: str,
    *,
    shelf_life: ShelfLife | None = None,
    staple: bool | None = None,
    availability: str | None = None,
) -> dict[str, Any]:
    """Put an article in a department — the one tap that turns unknown into known."""
    store = ctx.store
    if department != UNKNOWN_DEPARTMENT and store.department(department) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_department",
            translation_placeholders={"department": department},
        )

    known = store.ensure_article(article)
    known.department = department
    known.department_source = DepartmentSource.MANUAL
    department_model = store.department(department)
    known.kind = department_model.kind if department_model else None
    known.shelf_life = (
        shelf_life
        if shelf_life is not None
        else (department_model.shelf_life if department_model else ShelfLife.IGNORE)
    )
    if staple is not None:
        known.staple = staple
    if availability is not None:
        known.availability = availability or None

    # Anything already on a list moves with it.
    for list_name in (ListName.SHOPPING, ListName.LATER, ListName.STOCK):
        for item in store.items(list_name):
            if item.article == article:
                item.department = department
        store.sort_list(list_name, ctx.selected_store)

    ctx.commit()
    return {"article": known.name, "department": known.department, "kind": known.kind}


def set_window(
    ctx: Context,
    *,
    end: date | None = None,
    extend_days: int | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    """Stretch the menu window, or put it back.

    A stretched window never lapses quietly; it stays until someone resets it,
    and the screen says it is stretched.
    """
    store = ctx.store
    if reset:
        store.data.window_end = None
    elif end is not None:
        store.data.window_end = end
    elif extend_days:
        current = ctx.window()
        store.data.window_end = current.end + timedelta(days=extend_days)

    ctx.commit()
    window = ctx.window()
    return {"start": window.start.isoformat(), "end": window.end.isoformat(), "extended": window.extended}


# --------------------------------------------------------------------- reading


async def get_week(ctx: Context, start: date | None = None) -> dict[str, Any]:
    """Return a week's menu, with what the calendars already hold for each day.

    Every AI flow starts here. Without it a model proposes a menu for a Sunday
    the household is spending somewhere else.
    """
    window = ctx.window()
    first = start or window.start
    last = first + timedelta(days=len(window.days) - 1) if start else window.end

    events = await _calendar_events(ctx, first, last)
    store = ctx.store

    days = []
    for day in _dates(first, last):
        entry = store.day(day)
        days.append(
            {
                "date": day.isoformat(),
                "weekday": weekday_key(day),
                "dish": entry.dish,
                "note": entry.note,
                "people": entry.people,
                "calendar": events.get(day, []),
            }
        )
    return {"start": first.isoformat(), "end": last.isoformat(), "extended": window.extended, "days": days}


def list_dishes(ctx: Context) -> dict[str, Any]:
    """Return every dish, with what is known about when it is eaten and what goes in it."""
    store = ctx.store
    dishes = []
    for name, dish in sorted(store.data.dishes.items()):
        last = store.dish_last(name, ctx.today)
        dishes.append(
            {
                "name": name,
                "times": store.dish_times(name),
                "last": last.isoformat() if last else None,
                "days_since": (ctx.today - last).days if last else None,
                "usual_day": dish.usual_day,
                "interval_days": dish.interval_days,
                "fresh": store.dish_ingredients(name, Kind.FRESH),
                "pantry": store.dish_ingredients(name, Kind.PANTRY),
                "unclassified": [i.article for i in dish.ingredients if store.article_kind(i.article) is None],
            }
        )
    return {"dishes": dishes}


def get_history(
    ctx: Context,
    *,
    since: date | None = None,
    until: date | None = None,
    article: str | None = None,
    dish: str | None = None,
    kind: EventKind | None = None,
    limit: int = DEFAULT_HISTORY_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Return what has happened, most recent first.

    Two questions with one answer. Without filters this is the whole history, a
    page at a time — the response carries `total` and `returned`, so a caller
    that wants everything knows whether to ask again rather than being told no.
    With filters it is the everyday question: when did we last buy coffee, how
    often did we have tacos this year.

    Answers rather than a blob. `export_knowledge` hands over everything at
    once, which is the right shape for a backup and the wrong one for a model
    that has a question.
    """
    events = ctx.store.data.events
    if since is not None:
        events = [event for event in events if event.on >= since]
    if until is not None:
        events = [event for event in events if event.on <= until]
    if article is not None:
        folded = article.casefold().strip()
        events = [event for event in events if event.article and event.article.casefold() == folded]
    if dish is not None:
        folded = dish.casefold().strip()
        events = [event for event in events if event.dish and event.dish.casefold() == folded]
    if kind is not None:
        events = [event for event in events if event.kind == kind]

    # Most recent first: a question about a household's history is almost
    # always about the recent end of it.
    events = sorted(events, key=lambda event: event.on, reverse=True)
    total = len(events)
    window = events[max(offset, 0) : max(offset, 0) + max(min(limit, MAX_HISTORY_LIMIT), 1)]

    return {
        "total": total,
        "returned": len(window),
        "offset": max(offset, 0),
        "events": [event.to_dict() for event in window],
    }


def get_list(
    ctx: Context,
    list_name: ListName = ListName.SHOPPING,
    *,
    include_completed: bool = False,
) -> dict[str, Any]:
    """Return one list, grouped under department headings in walking order.

    The to-do entity can only hand out flat items with a summary and a
    description, which is exactly what made the paper list better than every
    app that came before it: the paper had headings. This is the same list the
    printable page renders, in the same order, so screen and paper never
    disagree.
    """
    store = ctx.store
    items = store.items(list_name) if include_completed else store.open_items(list_name)

    grouped: dict[str, list[Any]] = {}
    for item in items:
        grouped.setdefault(item.department, []).append(item)

    order = [key for key in store.store_order(ctx.selected_store) if key in grouped]
    order += [key for key in grouped if key not in order]

    return {
        "list": str(list_name),
        "store": ctx.selected_store,
        "open": len(store.open_items(list_name)),
        "completed": sum(1 for item in store.items(list_name) if item.completed),
        "groups": [
            {
                "department": key,
                "label": store.department_label(key, ctx.language),
                "items": [
                    {
                        "uid": item.uid,
                        "summary": item.summary,
                        "note": item.note,
                        "availability": item.availability,
                        "due": item.due.isoformat() if item.due else None,
                        "days_left": (item.due - ctx.today).days if item.due else None,
                        "added_on": item.added_on.isoformat() if item.added_on else None,
                        "days_ago": (ctx.today - item.added_on).days if item.added_on else None,
                        "dish": item.dish,
                        "article": item.article,
                        "completed": item.completed,
                    }
                    for item in grouped[key]
                ],
            }
            for key in order
        ],
    }


def get_pantry_check(ctx: Context, scope: PantryScope = PantryScope.GENERAL) -> dict[str, Any]:
    """Return what to go and check you still have.

    Exactly the pantry articles: the fresh ones you are buying anyway. That is
    what makes the answer short enough to act on standing at an open cupboard.

    Ordered by weight, not by name. Being on this list already means the filter
    decided it was urgent, so urgency cannot also be the sort key; what is left
    to say is which of them matters most to this household. Coffee and cat food
    come first and stay first, which is what makes the order worth remembering
    from one round to the next.
    """
    store = ctx.store
    if scope == PantryScope.MENU:
        window = ctx.window()
        names: list[str] = []
        for dish in store.planned_dishes(window.start, window.end):
            names += [name for name in store.dish_ingredients(dish, Kind.PANTRY) if name not in names]
        reasons = dict.fromkeys(names, "menu")
    else:
        reasons = _due_pantry_articles(ctx)
        names = list(reasons)

    names.sort(key=lambda name: _pantry_weight(ctx, name))

    on_list = {item.summary.casefold() for item in store.open_items(ListName.SHOPPING)}
    return {
        "scope": str(scope),
        "checked_today": len(store.checks_on(ctx.today, str(Round.PANTRY))),
        "articles": [
            {
                "article": name,
                "reason": reasons[name],
                "last_listed": last.isoformat() if (last := store.last_listed(name)) else None,
                "last_checked": checked.isoformat() if (checked := store.last_checked(name)) else None,
                "cadence_days": store.cadence_days(name),
                "already_listed": name.casefold() in on_list,
            }
            for name in names
        ],
    }


def _pantry_weight(ctx: Context, name: str) -> tuple[int, str, str]:
    """Return the sort key for one row of a cupboard round.

    Most often bought first, and on a tie the one longest unlooked-at. Counted
    from listings rather than purchases, because that is what forty sheets of
    paper can tell us: they record what was written down, never what came
    through the door. Every purchase begins as a listing, so as a *ranking* the
    two agree, and the purchases refine it from here on by themselves.
    """
    article = ctx.store.article(name)
    checked = ctx.store.last_checked(name)
    return (-(article.times if article else 0), checked.isoformat() if checked else "", name)


def _due_pantry_articles(ctx: Context) -> dict[str, str]:
    """Return the pantry articles to check, and why.

    A seeded article knows how often it comes round but not when it last did —
    the knowledge file carries a cadence, not a date. Until this installation
    has watched the article itself — seen it go onto a list, or been told at a
    cupboard that there is still plenty — "is it due?" has no honest answer, and
    returning nothing at all would make the whole question useless on a freshly
    seeded system.

    So there are two reasons an article shows up: `cadence`, once there is
    something to measure against, and `no_history` for the staples we simply
    have not watched long enough yet. The second kind disappears by itself as
    the first kind takes over.
    """
    store = ctx.store
    due: dict[str, str] = {}
    for article in store.data.articles.values():
        if store.article_kind(article.name) != Kind.PANTRY:
            continue
        if store.last_answer(article.name) is not None:
            if store.is_due(article.name, ctx.today):
                due[article.name] = "cadence"
        elif article.staple:
            due[article.name] = "no_history"
    return due


def get_expiring(ctx: Context, days: int = DEFAULT_EXPIRY_HORIZON_DAYS) -> dict[str, Any]:
    """Return what goes off within so many days."""
    horizon = ctx.today + timedelta(days=max(days, 0))
    items = [item for item in ctx.store.open_items(ListName.STOCK) if item.due is not None and item.due <= horizon]
    items.sort(key=lambda item: item.due)  # type: ignore[arg-type, return-value]
    return {
        "days": days,
        "articles": [
            {
                "article": item.summary,
                "expiry": item.due.isoformat(),  # type: ignore[union-attr]
                "days_left": (item.due - ctx.today).days,  # type: ignore[operator]
            }
            for item in items
        ],
        "undated": [
            {
                "article": item.summary,
                "added": item.added_on.isoformat() if item.added_on else None,
                "days_ago": (ctx.today - item.added_on).days if item.added_on else None,
            }
            for item in ctx.store.open_items(ListName.STOCK)
            if item.due is None
        ],
    }


def suggest_menu(
    ctx: Context,
    *,
    start: date | None = None,
    days: int | None = None,
    limit: int = DEFAULT_SUGGESTION_LIMIT,
) -> dict[str, Any]:
    """Suggest dishes — not a shopping list.

    Three signals, all of them measured rather than guessed: how often a dish
    comes round and how long ago it last did, which weekday it belongs to, and
    what is about to go off. The last is the strongest, because it is a lookup
    instead of a guess: there is mince that expires Thursday, so which dishes
    use mince?

    Variety is asked as a separate question. Ranking answers "what fits?", and
    a fitness score will always favour what the household eats anyway; mixing
    "we have not had this in ages" into the same number produces neither. So
    the ranking stays about fitting, and one clearly marked `wildcard` carries
    the other question.
    """
    store = ctx.store
    window = ctx.window()
    first = start or window.start
    span = days if days is not None else len(window.days)
    expiring = {item["article"] for item in get_expiring(ctx, DEFAULT_EXPIRY_HORIZON_DAYS)["articles"]}

    empty_days = [day for day in _dates(first, first + timedelta(days=max(span, 1) - 1)) if not store.day(day).dish]
    scored = {day: _score_dishes(ctx, day, expiring) for day in empty_days}
    reserved = _reserve(scored)

    suggestions = []
    for day in empty_days:
        mine = reserved.get(day)
        elsewhere = {dish for other, dish in reserved.items() if other != day}
        candidates = [c for c in scored[day] if c["dish"] == mine or c["dish"] not in elsewhere]
        candidates.sort(key=lambda c: (c["dish"] != mine, -c["score"]))
        suggestions.append({"date": day.isoformat(), "weekday": weekday_key(day), "candidates": candidates[:limit]})

    # Only the top pick of each day counts as "already proposed". Excluding
    # every third-choice candidate as well would mean that with a rotation of
    # any normal size there is never a wildcard at all — every dish appears
    # somewhere in seven days of three suggestions.
    proposed = {day["candidates"][0]["dish"] for day in suggestions if day["candidates"]}
    return {
        "start": first.isoformat(),
        "suggestions": suggestions,
        "wildcard": _wildcard(ctx, proposed),
    }


def _wildcard(ctx: Context, proposed: set[str]) -> dict[str, Any] | None:
    """Return one dish it has been a long time since, or None.

    Seven of this household's dishes were eaten exactly once. They have no
    interval, so they score nothing, so they were never suggested — while a dish
    with a bogus interval was suggested every single day. Both of those are the
    ranking failing at variety, which is why variety is asked separately.

    The one furthest back wins, so the list works its way through rather than
    offering the same forgotten dish forever.
    """
    store = ctx.store
    candidates: list[tuple[date, str]] = []
    for name in store.data.dishes:
        if name in proposed or store.dish_dormant(name, ctx.today):
            continue
        last = store.dish_last(name, ctx.today)
        if last is None or (ctx.today - last).days < WILDCARD_MIN_DAYS:
            continue
        candidates.append((last, name))

    if not candidates:
        return None
    last, name = min(candidates)
    return {"dish": name, "last": last.isoformat(), "days_since": (ctx.today - last).days}


def _reserve(scored: dict[date, list[dict[str, Any]]]) -> dict[date, str]:
    """Give each dish the day it fits best, rather than the first day that asks.

    Without this, a window that starts on Saturday hands Saturday the dish that
    belongs on Friday, simply because Saturday came first. Taking the strongest
    pairing each time puts tacos back on Friday where they belong.
    """
    pairs = sorted(
        ((candidate["score"], day, candidate["dish"]) for day, cands in scored.items() for candidate in cands),
        key=lambda pair: (-pair[0], pair[1], pair[2]),
    )
    reserved: dict[date, str] = {}
    used: set[str] = set()
    for _score, day, dish in pairs:
        if day in reserved or dish in used:
            continue
        reserved[day] = dish
        used.add(dish)
    return reserved


def _score_dishes(ctx: Context, day: date, expiring: set[str]) -> list[dict[str, Any]]:
    """Rank the dishes for one day, with the reasons attached.

    The overdue signal is the delicate one. An interval measured from a single
    gap is not a rhythm: two dishes eaten six days apart, once, two years ago
    produce "interval: 6 days" and are thereafter permanently, maximally
    overdue — which is exactly how a dish nobody has made since 2025 came to
    outrank one eaten thirty-six times. `store.dish_rhythm` refuses to call
    that a rhythm, and a dormant dish is left out altogether.
    """
    store = ctx.store
    weekday = weekday_key(day)
    scored: list[dict[str, Any]] = []

    for name, dish in store.data.dishes.items():
        if store.dish_dormant(name, ctx.today):
            continue

        score = 0.0
        reasons: list[str] = []

        uses_expiring = [article for article in store.dish_ingredients(name) if article in expiring]
        if uses_expiring:
            score += SCORE_EXPIRING
            reasons.append("expiring:" + ", ".join(uses_expiring))

        if dish.usual_day == weekday:
            score += SCORE_USUAL_DAY
            reasons.append("usual_day")

        last = store.dish_last(name, ctx.today)
        rhythm = store.dish_rhythm(name)
        if last is not None and rhythm:
            overdue = (ctx.today - last).days / rhythm
            if overdue >= 1:
                score += SCORE_OVERDUE * min(overdue, 3)
                reasons.append("overdue")
        elif last is None:
            reasons.append("never_planned")

        score += SCORE_FREQUENCY * store.dish_times(name)

        if score > 0:
            scored.append({"dish": name, "score": round(score, 1), "reasons": reasons})

    scored.sort(key=lambda candidate: candidate["score"], reverse=True)
    return scored


# ---------------------------------------------------------------------- helpers


def _dates(first: date, last: date) -> list[date]:
    """Return every date between two, inclusive."""
    count = (last - first).days + 1
    return [first + timedelta(days=offset) for offset in range(max(count, 0))]


async def _calendar_events(ctx: Context, first: date, last: date) -> dict[date, list[dict[str, Any]]]:
    """Read the configured calendars for a window.

    Reading only. Nothing in this integration ever writes to a calendar the user
    owns, not even the menu.
    """
    calendars = plan_options(ctx.entry).calendars
    if not calendars:
        return {}

    start = dt_util.as_local(datetime.combine(first, time.min))
    end = dt_util.as_local(datetime.combine(last + timedelta(days=1), time.min))

    try:
        response = await ctx.hass.services.async_call(
            "calendar",
            "get_events",
            {"start_date_time": start.isoformat(), "end_date_time": end.isoformat()},
            target={"entity_id": list(calendars)},
            blocking=True,
            return_response=True,
        )
    except Exception:  # noqa: BLE001 - a missing calendar must not break the menu
        return {}

    by_day: dict[date, list[dict[str, Any]]] = {}
    for entity_id, payload in (response or {}).items():
        for event in (payload or {}).get("events", []):
            begins = _event_date(event.get("start"))
            if begins is None:
                continue
            all_day = "T" not in str(event.get("start"))
            # An all-day event ends the morning after its last day.
            finishes = _event_date(event.get("end")) or begins
            last_day = finishes - timedelta(days=1) if all_day and finishes > begins else finishes
            for day in _dates(max(begins, first), min(last_day, last)):
                by_day.setdefault(day, []).append(
                    {"summary": event.get("summary"), "calendar": entity_id, "all_day": all_day}
                )
    return by_day


def _event_date(value: Any) -> date | None:
    """Reduce a calendar event start or end to a plain date."""
    if not value:
        return None
    text = str(value)
    try:
        if "T" in text:
            return dt_util.as_local(datetime.fromisoformat(text)).date()
        return date.fromisoformat(text)
    except ValueError:
        return None
