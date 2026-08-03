# Meal Plan

A Home Assistant integration for the weekly household ritual: **plan the meals,
fill the shopping list, walk the shop.**

It owns the domain rather than gluing helpers together. A shopping list that is
sorted in the order you actually walk the store, a meal plan that reads your
calendars but never writes to them, and a small body of knowledge — dishes,
articles, departments — that grows as you use it.

Everything works without AI. If you do want AI, the same set of tools is exposed
to both the [MCP server](https://www.home-assistant.io/integrations/mcp_server/)
and [Assist](https://www.home-assistant.io/voice_control/), through one
implementation.

## What it gives you

| Entity | What it is |
| --- | --- |
| `todo.<name>_shopping_list` | The shopping list. Departments in walking order, reorderable, due dates, descriptions. |
| `todo.<name>_stock` | Perishables you want to keep an eye on, with the expiry date as the due date. Not a stock count. |
| `calendar.<name>_meal_plan` | One all-day event per planned day. Publication only — your own calendars are never written to. |
| `select.<name>_store` | Which store you are shopping at; decides the department order the list is sorted in. |
| `sensor.<name>` | Summary plus attributes for the dashboard cards. |

### Services

*Writing*

| Service | What it does |
| --- | --- |
| `mealplan.add_dish` | Puts the fresh ingredients of a dish on the list. Pantry ingredients are reported back, not added. |
| `mealplan.running_low` | One article onto the list, `when: now` or `when: later`. |
| `mealplan.plan_menu` | A dish on a date, with an optional free-text note and number of people. |
| `mealplan.complete_all` | Complete everything, optionally `except_items` — "got everything except the sausages". |
| `mealplan.sort_list` | Reorder the open items into the department order of the selected store. |
| `mealplan.set_expiry` | Record an expiry date for an article. |
| `mealplan.learn_dish` | Teach it a new dish and its ingredients. |
| `mealplan.import_knowledge` / `export_knowledge` | Seed from a knowledge file / hand the current knowledge back. |

*Reading — every AI flow starts here*

| Service | What it does |
| --- | --- |
| `mealplan.get_week` | A week's menu, with the calendar entries and day notes per day. |
| `mealplan.list_dishes` | Every dish with its frequency, last served, usual weekday and ingredients. |
| `mealplan.get_pantry_check` | What to check: `general` (pantry articles due by their cadence) or `menu` (pantry articles of the planned dishes). |
| `mealplan.get_expiring` | What expires within N days. |
| `mealplan.suggest_menu` | Suggests **dishes** — from frequency, last served, the usual weekday, and what is about to expire. |

## Design decisions worth knowing

**It never writes to your calendars.** It reads the calendars you select, so the
meal plan can show what the day already holds. Writing is one-way: into its own
`calendar.<name>_meal_plan`, which you are free to ignore. A day note lives with
the plan, not in any calendar.

**A department is not a store aisle.** Articles belong to language-neutral
departments (`produce`, `butcher`, `frozen`, …); each store has its own order
over those departments. Move house, and you reorder the store, not the articles.

**Fresh and pantry are different management models.** A fresh article gets onto
the list *because a meal is planned*. A pantry article gets there *because it ran
low* — planning a dish never adds it. That distinction is what makes "what should
we check we still have?" a short, useful answer.

**Not every expiry date matters equally.** Cheese keeps for weeks; minced meat
does not. Articles carry `important`, `near_only` or `ignore`, defaulting from
their department. Only `important` ones are asked about.

**Classification never blocks.** "Something for the party" goes on the list
with no department, no category, no question. It lands in `unknown` at the
bottom. Only when the same item shows up a third time is learning it suggested,
and then only in passing.

**It works with an empty knowledge base.** Seeding is an accelerator, not a
prerequisite: you get the 13 default departments and nothing else, and the
knowledge grows as you use it.

## Installation

Through [HACS](https://hacs.xyz) as a custom repository:

1. HACS → three-dot menu → *Custom repositories*
1. Add `https://github.com/michiel-dewilde/ha-mealplan`, category *Integration*
1. Install *Meal Plan*, restart Home Assistant
1. *Settings → Devices & services → Add integration → Meal Plan*

Requires Home Assistant 2026.7.0 or newer.

## Configuration

The config flow asks for a name, the calendars to read, and the planning cycle.
All of it can be changed afterwards through the options flow.

| Option | Default | What it does |
| --- | --- | --- |
| Calendars | none | Which calendars are read for the day column. Never written to. |
| Week start | Saturday | First day of the menu window. |
| Menu days | 7 | Length of the window. |
| Roll over on | Thursday | The day the window moves to the next week. |
| Undated stock items | on | Whether `todo.<name>_stock` accepts items without an expiry date. They stay until you complete them; nothing ever disappears on its own. |

## Language

The interface ships in English and Dutch, both complete. The *content* — dish
names, article names, store names — is whatever you seeded or typed, and is never
translated.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and pull requests are
welcome.

## Licence

[GPL-3.0-or-later](LICENSE). Copyright © 2026 Michiel De Wilde.
