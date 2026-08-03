# SPDX-License-Identifier: GPL-3.0-or-later
"""The default department list.

Thirteen departments, seeded into the store the first time the integration is
set up. From that moment on it is user data: a later version of this integration
does not overwrite it. Users add, rename, reorder and delete as their own shop
demands.

The list is deliberately generic — a description of how supermarkets are laid
out, not of one household's habits. Which article belongs where is user data and
lives nowhere in this file.
"""

from __future__ import annotations

from typing import Final

from .const import Kind, ShelfLife

DEFAULT_DEPARTMENTS: Final[list[dict[str, object]]] = [
    {
        "key": "produce",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Produce", "nl": "Groenten & fruit"},
    },
    {
        "key": "bakery",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Bakery", "nl": "Brood & banket"},
    },
    {
        "key": "butcher",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.IMPORTANT,
        "labels": {"en": "Butcher", "nl": "Beenhouwerij"},
    },
    {
        "key": "fish",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.IMPORTANT,
        "labels": {"en": "Fish", "nl": "Vis"},
    },
    {
        "key": "chilled",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.NEAR_ONLY,
        "labels": {"en": "Chilled & deli", "nl": "Koelvak & traiteur"},
    },
    {
        "key": "dairy",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.NEAR_ONLY,
        "labels": {"en": "Dairy & cheese", "nl": "Zuivel & kaas"},
    },
    {
        "key": "dry_goods",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Dry goods", "nl": "Droge voeding"},
    },
    {
        "key": "preserves",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Preserves & sauces", "nl": "Conserven & sauzen"},
    },
    {
        "key": "drinks",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Drinks", "nl": "Dranken"},
    },
    {
        "key": "frozen",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Frozen", "nl": "Diepvries"},
    },
    {
        "key": "household",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Household & cleaning", "nl": "Onderhoud & huishouden"},
    },
    {
        "key": "personal_care",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Personal care", "nl": "Hygiëne & verzorging"},
    },
    {
        "key": "pet",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Pet supplies", "nl": "Huisdier"},
    },
]
