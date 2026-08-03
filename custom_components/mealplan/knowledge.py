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

from .const import DOMAIN, KNOWLEDGE_SCHEMA
from .models import Article, Department, Dish, StoreOrder
from .store import MealPlanStore


def import_knowledge(store: MealPlanStore, payload: dict[str, Any], *, replace: bool = False) -> dict[str, Any]:
    """Seed the store from a knowledge file.

    What the file carries wins; what it leaves out the integration keeps. That
    holds for the department list in particular: it is user data from the moment
    it is first seeded, and importing a file that never mentions `pet` does not
    delete `pet`.
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

    for raw in payload.get("articles") or []:
        article = Article.from_dict(raw)
        # A live count that has grown past the seeded one is the truer number.
        existing = data.articles.get(article.name)
        if existing is not None:
            article.times = max(article.times, existing.times)
            article.expiry_seen = article.expiry_seen or existing.expiry_seen
        data.articles[article.name] = article

    for raw in payload.get("dishes") or []:
        dish = Dish.from_dict(raw)
        data.dishes[dish.name] = dish

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
    }


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
