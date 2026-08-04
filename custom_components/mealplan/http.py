# SPDX-License-Identifier: GPL-3.0-or-later
"""The printable list.

Paper is a first-class way to shop here, not a fallback: one A4, two columns,
department headings in the walking order of the selected store, a box in front
of every item. The circle closes back in the app with `complete_all` —
"got everything except the sausages".

Two columns is the default because the lists that inspired this run from four to
thirty-odd items: one column would leave the short ones looking empty and the
long ones spilling onto a second page.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PRINT_URL, ListName
from .options import plan_options

if TYPE_CHECKING:
    from .types import MealPlanConfigEntry

STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  margin: 0; padding: 16px; color: #111; background: #fff;
  -webkit-text-size-adjust: 100%;
}
/* Stacked by default: on a phone the title and the meta line do not share a row. */
header { border-bottom: 1.5px solid #111; padding-bottom: 5px; margin-bottom: 10px; }
h1 { font-size: 19px; margin: 0; letter-spacing: .01em; overflow-wrap: anywhere; }
.meta { display: block; font-size: 12px; color: #555; margin-top: 2px; }
/* One column by default so a phone can read it; two only where there is room. */
.columns { column-count: 1; }
section { break-inside: avoid-column; margin: 0 0 14px; }
h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .07em;
  margin: 0 0 3px; padding-bottom: 2px; border-bottom: 1px solid #bbb; color: #333; }
ul { list-style: none; margin: 0; padding: 0; }
li { font-size: 15px; line-height: 1.6; display: flex; gap: 8px; align-items: baseline;
  break-inside: avoid; }
li > span:last-child { min-width: 0; overflow-wrap: anywhere; }
.box { flex: 0 0 auto; width: 12px; height: 12px; border: 1px solid #333;
  border-radius: 2px; display: inline-block; position: relative; top: 1px; }
.tag { font-size: 11px; color: #666; border: 1px solid #bbb; border-radius: 3px;
  padding: 0 4px; margin-left: 4px; white-space: nowrap; }
.note { font-size: 12px; color: #666; }
.empty { font-size: 15px; color: #777; font-style: italic; }
footer { margin-top: 20px; font-size: 11px; color: #888; }

@media screen and (min-width: 700px) {
  body { padding: 28px 32px; }
  .columns { column-count: 2; column-gap: 40px; column-fill: balance; }
  header { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; }
  .meta { margin-top: 0; }
}

@media print {
  body { padding: 10mm; }
  header { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; }
  h1 { font-size: 15pt; }
  .meta { font-size: 9pt; margin-top: 0; }
  h2 { font-size: 9.5pt; }
  li { font-size: 11pt; line-height: 1.55; }
  .box { width: 3.2mm; height: 3.2mm; border-width: .8px; }
  section { margin: 0 0 5mm; }
  .columns { column-count: 2; column-gap: 10mm; column-fill: balance; }
  footer { margin-top: 6mm; font-size: 8pt; }
  @page { size: A4 portrait; margin: 0; }
}
"""


class MealPlanPrintView(HomeAssistantView):
    """Serves the shopping list as a page you can print."""

    url = PRINT_URL + "/{entry_id}"
    name = f"api:{DOMAIN}:print"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Render the list for one config entry."""
        hass: HomeAssistant = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
            return web.Response(status=404, text="Unknown meal plan")
        return web.Response(text=render_list(hass, entry), content_type="text/html")


def render_list(hass: HomeAssistant, entry: MealPlanConfigEntry) -> str:
    """Render the open shopping list as a printable HTML page."""
    store = entry.runtime_data.store
    language = hass.config.language
    chosen = entry.runtime_data.store_choice
    items = store.open_items(ListName.SHOPPING)

    grouped: dict[str, list] = {}
    for item in items:
        grouped.setdefault(item.department, []).append(item)

    order = [key for key in store.store_order(chosen) if key in grouped]
    order += [key for key in grouped if key not in order]

    sections = []
    for key in order:
        rows = "".join(_render_item(item) for item in grouped[key])
        heading = escape(store.department_label(key, language))
        sections.append(f"<section><h2>{heading}</h2><ul>{rows}</ul></section>")

    body = "".join(sections) or '<p class="empty">Nothing on the list.</p>'
    later = store.open_items(ListName.LATER)
    if later:
        rows = "".join(_render_item(item) for item in later)
        body += f"<section><h2>{escape(_later_heading(language))}</h2><ul>{rows}</ul></section>"

    options = plan_options(entry)
    meta = escape(chosen or "") if chosen else ""
    count = len(items)

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(entry.title)}</title><style>{STYLE}</style></head><body>"
        f"<header><h1>{escape(entry.title)}</h1>"
        f"<span class='meta'>{meta}{' · ' if meta else ''}{count} items</span></header>"
        f"<div class='columns'>{body}</div>"
        f"<footer>{escape(_footer(language, options.week_start))}</footer>"
        "</body></html>"
    )


def _render_item(item) -> str:  # noqa: ANN001 - a ListItem, kept loose to avoid a cycle
    """Render one line: a box, the name, and any markers."""
    tag = f"<span class='tag'>{escape(item.availability)}</span>" if item.availability else ""
    note = f" <span class='note'>{escape(item.note)}</span>" if item.note else ""
    return f"<li><span class='box'></span><span>{escape(item.summary)}{tag}{note}</span></li>"


def _later_heading(language: str) -> str:
    """Return the heading for the next-trip block."""
    return "Volgende beurt" if language == "nl" else "Next trip"


def _footer(language: str, week_start: str) -> str:
    """Return the footer line."""
    del week_start
    return "Afgedrukt uit Home Assistant" if language == "nl" else "Printed from Home Assistant"
