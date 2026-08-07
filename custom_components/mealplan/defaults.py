# SPDX-License-Identifier: GPL-3.0-or-later
"""The default department list.

Sixteen departments, seeded into the store the first time the integration is
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
    # Two departments rather than one "chilled": the word describes the
    # refrigeration and not the contents — dairy and meat are chilled too — and
    # in practice the shelf holds meat substitutes on one side and spreads and
    # ready-made salads on the other. Two headings that mean something, instead
    # of one that means "cold".
    {
        "key": "veggie",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.NEAR_ONLY,
        "labels": {"en": "Meat substitutes", "nl": "Vleesvervangers"},
    },
    {
        "key": "deli",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.NEAR_ONLY,
        "labels": {"en": "Deli & spreads", "nl": "Traiteur & smeersels"},
    },
    {
        "key": "dairy",
        "kind": Kind.FRESH,
        "shelf_life": ShelfLife.NEAR_ONLY,
        "labels": {"en": "Dairy & cheese", "nl": "Zuivel & kaas"},
    },
    # Frozen is pantry, not fresh. Frozen peas go on the list because they ran
    # out, exactly like rice — not because a meal was planned. As `fresh` they
    # were added silently when planning a dish and never turned up in the
    # cupboard round, and both of those were wrong.
    {
        "key": "frozen",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Frozen", "nl": "Diepvries"},
    },
    {
        "key": "dry_goods",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Dry goods", "nl": "Droge voeding"},
    },
    {
        "key": "spices",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Herbs & spices", "nl": "Kruiden & specerijen"},
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
        "key": "household",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Household & cleaning", "nl": "Onderhoud & schoonmaak"},
    },
    # A saucepan, a tin opener and a hyacinth are not cleaning supplies. They
    # ended up there because "household" had quietly become "everything that is
    # not food", which put one-off purchases among the weekly shopping.
    {
        "key": "home",
        "kind": Kind.PANTRY,
        "shelf_life": ShelfLife.IGNORE,
        "labels": {"en": "Home & sundries", "nl": "Huis & varia"},
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
