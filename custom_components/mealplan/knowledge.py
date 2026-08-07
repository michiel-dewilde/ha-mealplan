# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading and writing the knowledge file.

Version 2.0 of the schema. Field names and enum values are English because they
are a contract; article names, dish names, store names and quoted source text
are free text in whatever language the household cooks in, and are passed
through untouched.

Importing is an accelerator, never a prerequisite. An installation that never
imports anything still has thirteen departments and learns the rest as it goes.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, KNOWLEDGE_SCHEMA, UNKNOWN_DEPARTMENT, DepartmentSource, ShelfLife
from .models import Article, Department, Dish, StoreOrder
from .store import MealPlanStore


def import_knowledge(store: MealPlanStore, payload: dict[str, Any], *, replace: bool = False) -> dict[str, Any]:
    """Seed the store from a knowledge file.

    What the file carries wins; what it leaves out the integration keeps. That
    holds for the department list in particular: it is user data from the moment
    it is first seeded, and importing a file that never mentions `pet` does not
    delete `pet`.

    With one exception, and it is the important one: an article someone placed
    by hand is never overwritten. `department_source: manual` is a decision, and
    a file is an opinion. The response lists what was kept, under `kept_manual`,
    so an import that ignored part of its own payload says so out loud.
    """
    schema = str(payload.get("schema") or "")
    if schema and not schema.startswith("2."):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unsupported_schema",
            translation_placeholders={"schema": schema, "expected": KNOWLEDGE_SCHEMA},
        )

    data = store.data

    departments = [Department.from_dict(d) for d in payload.get("departments") or []]
    if departments:
        if replace:
            data.departments = departments
        else:
            by_key = {d.key: d for d in data.departments}
            order = [d.key for d in departments]
            order += [key for key in by_key if key not in order]
            by_key.update({d.key: d for d in departments})
            data.departments = [by_key[key] for key in order]

    for name, raw in (payload.get("stores") or {}).items():
        data.stores[str(name)] = StoreOrder.from_dict(raw)

    kept: list[str] = []
    for raw in payload.get("articles") or []:
        article = Article.from_dict(raw)
        existing = data.articles.get(article.name)
        # What someone placed by hand outranks any file. Without this, every
        # regenerated knowledge base silently undoes the work done in the
        # management screen — and silently is the worst way to lose it.
        if existing is not None and existing.department_source == DepartmentSource.MANUAL:
            existing.times = max(article.times, existing.times)
            existing.cadence_days = existing.cadence_days or article.cadence_days
            existing.last_listed = max(
                (day for day in (existing.last_listed, article.last_listed) if day is not None),
                default=None,
            )
            kept.append(article.name)
            continue
        # A live count that has grown past the seeded one is the truer number.
        if existing is not None:
            article.times = max(article.times, existing.times)
            article.expiry_seen = article.expiry_seen or existing.expiry_seen
        data.articles[article.name] = article

    for raw in payload.get("dishes") or []:
        dish = Dish.from_dict(raw)
        data.dishes[dish.name] = dish
        _adopt_ingredient_articles(store, dish)

    data.source = {
        "schema": schema or KNOWLEDGE_SCHEMA,
        "generated": payload.get("generated"),
        **(payload.get("source") or {}),
    }

    store.async_schedule_save()
    return {
        "departments": len(data.departments),
        "stores": len(data.stores),
        "articles": len(data.articles),
        "dishes": len(data.dishes),
        "kept_manual": sorted(kept),
    }


def _adopt_ingredient_articles(store: MealPlanStore, dish: Dish) -> None:
    """Make sure every ingredient a dish names exists as an article.

    An ingredient is supposed to reference an article by name, but a knowledge
    file can list ingredients that never appeared on a shopping list under that
    name — a recipe asks for shallots, the list has always said onions. Without
    this, those ingredients land in `unknown` at the bottom of the list even
    though the file said which department they belong to.

    The ingredient's own department is what we go on: it is a statement about
    the article, and it is the only one we have.

    This also picks up articles that already exist but were never classified —
    typed onto a list once and left in `unknown`. A knowledge file that names
    the department is exactly the moment to place them. An article that already
    has a department is never touched: what the user or an earlier import
    decided outranks a recipe's opinion.
    """
    for ingredient in dish.ingredients:
        existing = store.data.articles.get(ingredient.article)
        if existing is not None and existing.department != UNKNOWN_DEPARTMENT:
            continue
        department = store.department(ingredient.department)
        if existing is not None and department is None:
            continue
        article = existing or Article(name=ingredient.article)
        article.department = ingredient.department if department else UNKNOWN_DEPARTMENT
        article.kind = department.kind if department else None
        article.department_source = DepartmentSource.RULE
        article.shelf_life = department.shelf_life if department else ShelfLife.IGNORE
        store.data.articles[article.name] = article


def export_knowledge(store: MealPlanStore, today: date) -> dict[str, Any]:
    """Hand the current knowledge back, seeded history and live history together.

    This is what keeps the knowledge from freezing the day it was seeded: `last`
    and `times` here are what the integration has actually seen since, not what
    was true when the file was written. Home Assistant does not push this
    anywhere — something outside fetches it, read-only, when its owner decides.
    """
    dishes = []
    for name, dish in sorted(store.data.dishes.items()):
        exported = dish.to_dict()
        exported["times"] = store.dish_times(name)
        last = store.dish_last(name, today)
        exported["last"] = last.isoformat() if last else None
        dishes.append(exported)

    articles = []
    for name, article in sorted(store.data.articles.items()):
        exported = article.to_dict()
        exported["cadence_days"] = store.cadence_days(name)
        articles.append(exported)

    return {
        "schema": KNOWLEDGE_SCHEMA,
        "generated": today.isoformat(),
        "source": store.data.source,
        "departments": [d.to_dict() for d in store.data.departments],
        "stores": {name: order.to_dict() for name, order in sorted(store.data.stores.items())},
        "articles": articles,
        "dishes": dishes,
        "plan": {day.isoformat(): entry.to_dict() for day, entry in sorted(store.data.plan.items())},
        "listings": [item.to_dict() for item in store.data.listings],
    }
