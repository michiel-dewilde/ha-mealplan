# SPDX-License-Identifier: GPL-3.0-or-later
"""The data model.

Mirrors version 2.0 of the knowledge file schema, plus the state the integration
maintains itself: the plan, and the purchase history that keeps "last eaten" from
going stale the day after seeding.

Free text — article names, dish names, store names, source quotes — is passed
through untouched. It is the user's data, in the user's language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Self

from .const import (
    UNKNOWN_DEPARTMENT,
    Certainty,
    DepartmentSource,
    IngredientSource,
    Kind,
    ShelfLife,
    StoreSource,
)


def _as_enum[T](enum: type[T], value: Any, fallback: T) -> T:
    """Coerce a stored string into an enum member, falling back if it is unknown.

    Data outlives code: a knowledge file may carry a value a later version
    dropped. Refusing to load the whole file over one stray string would be
    worse than quietly falling back.
    """
    try:
        return enum(value)
    except ValueError:
        return fallback


def _as_date(value: Any) -> date | None:
    """Parse an ISO date, tolerating null and rubbish."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass(slots=True)
class Department:
    """A section of the shop, independent of any particular store."""

    key: str
    kind: Kind = Kind.PANTRY
    shelf_life: ShelfLife = ShelfLife.IGNORE
    labels: dict[str, str] = field(default_factory=dict)

    def label(self, language: str) -> str:
        """Return the display label for a language, falling back to English then the key."""
        return self.labels.get(language) or self.labels.get("en") or self.key

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Build a department from stored or imported data."""
        return cls(
            key=str(data["key"]),
            kind=_as_enum(Kind, data.get("kind"), Kind.PANTRY),
            shelf_life=_as_enum(ShelfLife, data.get("shelf_life"), ShelfLife.IGNORE),
            labels={str(k): str(v) for k, v in (data.get("labels") or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage and export."""
        return {
            "key": self.key,
            "kind": str(self.kind),
            "shelf_life": str(self.shelf_life),
            "labels": dict(self.labels),
        }


@dataclass(slots=True)
class Article:
    """Something you buy, with everything needed to place it on a list."""

    name: str
    department: str = UNKNOWN_DEPARTMENT
    kind: Kind | None = None
    department_source: DepartmentSource = DepartmentSource.UNKNOWN
    times: int = 0
    last_listed: date | None = None
    """When this article was last on a list. Gives the cadence something to count from."""

    cadence_days: float | None = None
    staple: bool = False
    frozen: bool = False
    availability: str | None = None
    shelf_life: ShelfLife = ShelfLife.IGNORE
    expiry_seen: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Build an article from stored or imported data."""
        raw_kind = data.get("kind")
        cadence = data.get("cadence_days")
        return cls(
            name=str(data["name"]),
            department=str(data.get("department") or UNKNOWN_DEPARTMENT),
            kind=_as_enum(Kind, raw_kind, Kind.PANTRY) if raw_kind else None,
            department_source=_as_enum(DepartmentSource, data.get("department_source"), DepartmentSource.UNKNOWN),
            times=int(data.get("times") or 0),
            last_listed=_as_date(data.get("last_listed")),
            cadence_days=float(cadence) if cadence is not None else None,
            staple=bool(data.get("staple")),
            frozen=bool(data.get("frozen")),
            availability=data.get("availability") or None,
            shelf_life=_as_enum(ShelfLife, data.get("shelf_life"), ShelfLife.IGNORE),
            expiry_seen=bool(data.get("expiry_seen")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage and export."""
        return {
            "name": self.name,
            "department": self.department,
            "kind": str(self.kind) if self.kind else None,
            "department_source": str(self.department_source),
            "times": self.times,
            "last_listed": self.last_listed.isoformat() if self.last_listed else None,
            "cadence_days": self.cadence_days,
            "staple": self.staple,
            "frozen": self.frozen,
            "availability": self.availability,
            "shelf_life": str(self.shelf_life),
            "expiry_seen": self.expiry_seen,
        }


@dataclass(slots=True)
class Ingredient:
    """One article a dish needs, with how sure we are about it."""

    article: str
    certainty: Certainty = Certainty.CERTAIN
    source: IngredientSource = IngredientSource.MANUAL
    department: str = UNKNOWN_DEPARTMENT
    source_text: str | None = None
    coverage: float | None = None
    lift: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Build an ingredient from stored or imported data."""
        return cls(
            article=str(data["article"]),
            certainty=_as_enum(Certainty, data.get("certainty"), Certainty.CERTAIN),
            source=_as_enum(IngredientSource, data.get("source"), IngredientSource.MANUAL),
            department=str(data.get("department") or UNKNOWN_DEPARTMENT),
            source_text=data.get("source_text") or None,
            coverage=data.get("coverage"),
            lift=data.get("lift"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage and export, dropping the optional fields when empty."""
        data: dict[str, Any] = {
            "article": self.article,
            "certainty": str(self.certainty),
            "source": str(self.source),
            "department": self.department,
        }
        if self.source_text is not None:
            data["source_text"] = self.source_text
        if self.coverage is not None:
            data["coverage"] = self.coverage
        if self.lift is not None:
            data["lift"] = self.lift
        return data


@dataclass(slots=True)
class Dish:
    """A meal, under the name the household actually uses for it."""

    name: str
    times: int = 0
    last: date | None = None
    usual_day: str | None = None
    interval_days: float | None = None
    veggie_variants: int = 0
    recipe_list: str | None = None
    ingredients: list[Ingredient] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Build a dish from stored or imported data."""
        interval = data.get("interval_days")
        return cls(
            name=str(data["name"]),
            times=int(data.get("times") or 0),
            last=_as_date(data.get("last")),
            usual_day=data.get("usual_day") or None,
            interval_days=float(interval) if interval is not None else None,
            veggie_variants=int(data.get("veggie_variants") or 0),
            recipe_list=data.get("recipe_list") or None,
            ingredients=[Ingredient.from_dict(i) for i in data.get("ingredients") or []],
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage and export."""
        return {
            "name": self.name,
            "times": self.times,
            "last": self.last.isoformat() if self.last else None,
            "usual_day": self.usual_day,
            "interval_days": self.interval_days,
            "veggie_variants": self.veggie_variants,
            "recipe_list": self.recipe_list,
            "ingredients": [i.to_dict() for i in self.ingredients],
        }


@dataclass(slots=True)
class StoreOrder:
    """One store's walking route, as an order over department keys."""

    department_order: list[str] = field(default_factory=list)
    lists: int = 0
    source: StoreSource = StoreSource.MANUAL

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Build a store order from stored or imported data."""
        return cls(
            department_order=[str(d) for d in data.get("department_order") or []],
            lists=int(data.get("lists") or 0),
            source=_as_enum(StoreSource, data.get("source"), StoreSource.MANUAL),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage and export."""
        return {
            "department_order": list(self.department_order),
            "lists": self.lists,
            "source": str(self.source),
        }


@dataclass(slots=True)
class DayPlan:
    """What is planned for one day.

    All three fields are optional, and an empty day is a perfectly normal state —
    not a gap to be filled in. The note lives here and nowhere else; it is never
    written to a calendar.
    """

    dish: str | None = None
    note: str | None = None
    people: int | None = None

    @property
    def is_empty(self) -> bool:
        """Return whether this day carries no information at all."""
        return not self.dish and not self.note and self.people is None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Build a day plan from stored data."""
        people = data.get("people")
        return cls(
            dish=data.get("dish") or None,
            note=data.get("note") or None,
            people=int(people) if people is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage."""
        return {"dish": self.dish, "note": self.note, "people": self.people}


@dataclass(slots=True)
class ListItem:
    """One line on one of the to-do lists.

    Carries more than a `TodoItem` does: which department it belongs to, which
    dish put it there, where it is available, and when it was added. The last of
    those is what lets the stock list say "added 12 days ago" instead of quietly
    dropping things.
    """

    uid: str
    summary: str
    completed: bool = False
    due: date | None = None
    department: str = UNKNOWN_DEPARTMENT
    note: str | None = None
    availability: str | None = None
    added_on: date | None = None
    dish: str | None = None
    article: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Build a list item from stored data."""
        return cls(
            uid=str(data["uid"]),
            summary=str(data.get("summary") or ""),
            completed=bool(data.get("completed")),
            due=_as_date(data.get("due")),
            department=str(data.get("department") or UNKNOWN_DEPARTMENT),
            note=data.get("note") or None,
            availability=data.get("availability") or None,
            added_on=_as_date(data.get("added_on")),
            dish=data.get("dish") or None,
            article=data.get("article") or None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage."""
        return {
            "uid": self.uid,
            "summary": self.summary,
            "completed": self.completed,
            "due": self.due.isoformat() if self.due else None,
            "department": self.department,
            "note": self.note,
            "availability": self.availability,
            "added_on": self.added_on.isoformat() if self.added_on else None,
            "dish": self.dish,
            "article": self.article,
        }


@dataclass(slots=True)
class Listing:
    """One article, on one shopping list, on one day.

    Recorded when the article is put on the list. This is what keeps `times` and
    `cadence_days` alive after the seeded history has gone stale — the seeded
    counts and the live ones are added together, never one or the other.
    """

    article: str
    on: date

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self | None:
        """Build a listing from stored data, or None if the date is unusable."""
        on = _as_date(data.get("on"))
        if on is None:
            return None
        return cls(article=str(data["article"]), on=on)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage."""
        return {"article": self.article, "on": self.on.isoformat()}
