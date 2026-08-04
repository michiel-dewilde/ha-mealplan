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
    DOMAIN,
    SIGNAL_UPDATED,
    UNKNOWN_DEPARTMENT,
    Certainty,
    DepartmentSource,
    IngredientSource,
    Kind,
    ListName,
    PantryScope,
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
        """Persist and tell the entities to redraw."""
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
    """
    list_name = ListName.SHOPPING if when == When.NOW else ListName.LATER
    if (existing := ctx.store.find_by_summary(list_name, article)) is not None:
        return {"article": existing.summary, "list": str(list_name), "added": False}

    item = ctx.store.add_item(list_name, article, ctx.today)
    ctx.store.sort_list(list_name, ctx.selected_store)
    ctx.commit()
    return {"article": item.summary, "list": str(list_name), "added": True}


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
        item.completed = True
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


def get_pantry_check(ctx: Context, scope: PantryScope = PantryScope.GENERAL) -> dict[str, Any]:
    """Return what to go and check you still have.

    Exactly the pantry articles: the fresh ones you are buying anyway. That is
    what makes the answer short enough to act on standing at an open cupboard.
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
        names = sorted(reasons)

    on_list = {item.summary.casefold() for item in store.open_items(ListName.SHOPPING)}
    return {
        "scope": str(scope),
        "articles": [
            {
                "article": name,
                "reason": reasons[name],
                "last_listed": last.isoformat() if (last := store.last_listed(name)) else None,
                "cadence_days": store.cadence_days(name),
                "already_listed": name.casefold() in on_list,
            }
            for name in names
        ],
    }


def _due_pantry_articles(ctx: Context) -> dict[str, str]:
    """Return the pantry articles to check, and why.

    A seeded article knows how often it comes round but not when it last did —
    the knowledge file carries a cadence, not a date. Until this installation
    has seen the article go onto a list itself, "is it due?" has no honest
    answer, and returning nothing at all would make the whole question useless
    on a freshly seeded system.

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
        if store.last_listed(article.name) is not None:
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
    return {"start": first.isoformat(), "suggestions": suggestions}


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
    """Rank the dishes for one day, with the reasons attached."""
    store = ctx.store
    weekday = weekday_key(day)
    scored: list[dict[str, Any]] = []

    for name, dish in store.data.dishes.items():
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
        if last is not None and dish.interval_days:
            overdue = (ctx.today - last).days / dish.interval_days
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
