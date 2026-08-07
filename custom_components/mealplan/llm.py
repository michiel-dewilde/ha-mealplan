# SPDX-License-Identifier: GPL-3.0-or-later
"""The tools a language model gets.

One implementation, two consumers: the MCP server and Assist both take their
tools from here, so a change is never made twice and never made in only one
place.

Tool and parameter descriptions are English because that is what the model
reads; the data that comes back is in whatever language the household writes
in. The two are unrelated — Assist in Dutch works fine against English tool
descriptions.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util
from homeassistant.util.json import JsonObjectType
import voluptuous as vol

from . import api
from .const import DOMAIN, EventKind, ListName, PantryScope, Round, When
from .knowledge import export_knowledge
from .options import plan_options
from .types import MealPlanConfigEntry

type Handler = Callable[[api.Context, dict[str, Any]], Awaitable[JsonObjectType] | JsonObjectType]


class MealPlanTool(llm.Tool):
    """One tool, backed by one function in `api`."""

    def __init__(
        self,
        entry: MealPlanConfigEntry,
        name: str,
        description: str,
        parameters: vol.Schema,
        handler: Handler,
    ) -> None:
        """Bind a tool to a meal plan."""
        self.name = name
        self.description = description
        self.parameters = parameters
        self._entry = entry
        self._handler = handler

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        """Run the tool."""
        del llm_context
        ctx = api.context(hass, self._entry)
        result = self._handler(ctx, tool_input.tool_args)
        if isinstance(result, Awaitable):
            result = await result
        return result  # type: ignore[return-value]


def _tools(entry: MealPlanConfigEntry) -> list[llm.Tool]:
    """Build the toolset for one meal plan.

    Reading comes first on purpose. An earlier design had nine tools and not one
    of them returned the current state, which meant a model could only ever
    write over what it could not see.
    """

    def tool(name: str, description: str, parameters: dict[Any, Any], handler: Handler) -> MealPlanTool:
        return MealPlanTool(entry, name, description, vol.Schema(parameters), handler)

    return [
        # ------------------------------------------------------------ reading
        tool(
            "get_week",
            "Get the planned menu for a week, including each day's calendar entries and "
            "free-text day notes. Start here: without it you do not know what is already "
            "planned or what the household is already doing that day. An empty day is "
            "normal and deliberate, not a gap to fill.",
            {vol.Optional("start"): str},
            lambda ctx, args: api.get_week(ctx, dt_util.parse_date(args["start"]) if args.get("start") else None),
        ),
        tool(
            "list_dishes",
            "List every dish the household knows, with how often it is eaten, when it was "
            "last on the table, which weekday it usually falls on, and its fresh and "
            "pantry ingredients.",
            {},
            lambda ctx, args: api.list_dishes(ctx),
        ),
        tool(
            "get_history",
            "Read what has actually happened in this household: what went onto a list, "
            "what was bought, what was eaten, what was checked during a round. Most "
            "recent first. Without filters it returns the whole history a page at a time "
            "— the response carries `total`, `returned` and `offset`, so ask again with a "
            "higher offset to walk through all of it. With filters it answers the "
            "everyday question: when did we last buy coffee, how often did we have tacos.",
            {
                vol.Optional("since"): str,
                vol.Optional("until"): str,
                vol.Optional("article"): str,
                vol.Optional("dish"): str,
                vol.Optional("kind"): vol.In([str(kind) for kind in EventKind]),
                vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=1, max=api.MAX_HISTORY_LIMIT)),
                vol.Optional("offset"): vol.All(vol.Coerce(int), vol.Range(min=0)),
            },
            lambda ctx, args: api.get_history(
                ctx,
                since=dt_util.parse_date(args["since"]) if args.get("since") else None,
                until=dt_util.parse_date(args["until"]) if args.get("until") else None,
                article=args.get("article"),
                dish=args.get("dish"),
                kind=EventKind(args["kind"]) if args.get("kind") else None,
                limit=args.get("limit", api.DEFAULT_HISTORY_LIMIT),
                offset=args.get("offset", 0),
            ),
        ),
        tool(
            "get_list",
            "Read one of the three lists — 'shopping' for this trip, 'later' for the next "
            "one, 'stock' for what is in the house — grouped under department headings in "
            "the walking order of the selected store.",
            {
                vol.Optional("list"): vol.In([str(name) for name in ListName]),
                vol.Optional("include_completed"): bool,
            },
            lambda ctx, args: api.get_list(
                ctx,
                ListName(args.get("list", ListName.SHOPPING)),
                include_completed=args.get("include_completed", False),
            ),
        ),
        tool(
            "get_pantry_check",
            "List the pantry articles worth checking you still have. Scope 'general' is "
            "everything due by its own cadence; scope 'menu' is the pantry ingredients of "
            "the dishes currently planned. Fresh articles are not included: those get "
            "bought anyway.",
            {vol.Optional("scope"): vol.In([str(s) for s in PantryScope])},
            lambda ctx, args: api.get_pantry_check(ctx, PantryScope(args.get("scope", PantryScope.GENERAL))),
        ),
        tool(
            "get_expiring",
            "List what is in the house and goes off within a number of days. Use this "
            "before suggesting a menu: a dish that uses something about to expire is a "
            "lookup, not a guess.",
            {vol.Optional("days"): vol.All(vol.Coerce(int), vol.Range(min=0, max=365))},
            lambda ctx, args: api.get_expiring(ctx, args.get("days", api.DEFAULT_EXPIRY_HORIZON_DAYS)),
        ),
        tool(
            "suggest_menu",
            "Suggest dishes for the empty days in the planning window, ranked by what is "
            "about to expire, the usual weekday for a dish, how overdue it is, and how "
            "often it is eaten. Suggests dishes only — never a shopping list. Alongside "
            "the ranking it returns one `wildcard`: a dish it has been a long time since, "
            "offered as a deliberate change rather than as a good fit. Dishes nobody has "
            "eaten in eighteen months are dormant and are not suggested at all.",
            {
                vol.Optional("start"): str,
                vol.Optional("days"): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
                vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
            },
            lambda ctx, args: api.suggest_menu(
                ctx,
                start=dt_util.parse_date(args["start"]) if args.get("start") else None,
                days=args.get("days"),
                limit=args.get("limit", api.DEFAULT_SUGGESTION_LIMIT),
            ),
        ),
        # ------------------------------------------------------------ writing
        tool(
            "plan_menu",
            "Put a dish on a date, optionally with a free-text note for that day and a "
            "number of people. Does not touch the shopping list — topping the list up is "
            "always a separate, deliberate act. The note stays with the plan and is never "
            "written to any calendar.",
            {
                vol.Required("date"): str,
                vol.Optional("dish"): str,
                vol.Optional("note"): str,
                vol.Optional("people"): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
            },
            lambda ctx, args: api.plan_menu(
                ctx,
                dt_util.parse_date(args["date"]) or ctx.today,
                dish=args.get("dish"),
                note=args.get("note"),
                people=args.get("people"),
            ),
        ),
        tool(
            "add_dish",
            "Put a dish's fresh ingredients on the shopping list. Certain ingredients are "
            "added; less certain ones and pantry ingredients are returned for the user to "
            "confirm rather than added silently.",
            {
                vol.Required("dish"): str,
                vol.Optional("servings"): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
                vol.Optional("include_pantry"): bool,
            },
            lambda ctx, args: api.add_dish(
                ctx,
                args["dish"],
                servings=args.get("servings"),
                include_pantry=args.get("include_pantry", False),
            ),
        ),
        tool(
            "running_low",
            "Put one article that is running low on a list. 'now' means this shopping "
            "trip; 'later' means the next one.",
            {vol.Required("article"): str, vol.Optional("when"): vol.In([str(w) for w in When])},
            lambda ctx, args: api.running_low(ctx, args["article"], When(args.get("when", When.NOW))),
        ),
        tool(
            "check_off",
            "Record the answers a round produced: for each article, still enough or run "
            "out. 'Run out' is not just a note — on the cupboard round it puts the article "
            "on the list, on the fridge round it ticks it out of the house. Answering "
            "'still enough' counts for as much as buying it: the article goes quiet until "
            "its own cadence asks again. Leave the articles out to answer a whole round at "
            "once, which is only allowed for 'still enough'.",
            {
                vol.Optional("articles"): [str],
                vol.Optional("enough"): bool,
                vol.Optional("round"): vol.In([str(r) for r in Round]),
                vol.Optional("scope"): vol.In([str(s) for s in PantryScope]),
                vol.Optional("when"): vol.In([str(w) for w in When]),
            },
            lambda ctx, args: api.check_off(
                ctx,
                articles=args.get("articles"),
                enough=args.get("enough", True),
                round_name=Round(args.get("round", Round.PANTRY)),
                scope=PantryScope(args.get("scope", PantryScope.GENERAL)),
                when=When(args.get("when", When.NOW)),
            ),
        ),
        tool(
            "reset_round",
            "Withdraw today's answers to a round so it asks everything again. For a "
            "mis-tapped row or a round somebody left half done. Only today's answers go; "
            "anything those answers put on a list stays on that list.",
            {vol.Optional("round"): vol.In([str(r) for r in Round])},
            lambda ctx, args: api.reset_round(ctx, Round(args.get("round", Round.PANTRY))),
        ),
        tool(
            "move_item",
            "Move something from one list to another — typically from the next trip to "
            "this one. This is not a new listing and does not count as one: it is the same "
            "item, on a different list.",
            {vol.Required("item"): str, vol.Required("to"): vol.In([str(name) for name in ListName])},
            lambda ctx, args: api.move_item(ctx, args["item"], ListName(args["to"])),
        ),
        tool(
            "move_all",
            "Move everything still open on one list to another — 'the next trip is now "
            "this trip', at the moment a shopping round starts. Like moving one item, this "
            "records nothing and is not a new listing.",
            {
                vol.Required("to"): vol.In([str(name) for name in ListName]),
                vol.Optional("from"): vol.In([str(name) for name in ListName]),
            },
            lambda ctx, args: api.move_all(ctx, ListName(args["to"]), ListName(args.get("from", ListName.LATER))),
        ),
        tool(
            "complete_all",
            "Complete everything on the shopping list, optionally except the items named. "
            "This is the 'got everything except the sausages' case.",
            {vol.Optional("except_items"): [str]},
            lambda ctx, args: api.complete_all(ctx, args.get("except_items")),
        ),
        tool(
            "set_expiry",
            "Record the expiry date of something in the house. Asked for at home while "
            "putting the shopping away, never at the till.",
            {vol.Required("article"): str, vol.Required("expiry"): str},
            lambda ctx, args: api.set_expiry(ctx, args["article"], dt_util.parse_date(args["expiry"]) or ctx.today),
        ),
        tool(
            "learn_dish",
            "Teach the household a new dish and its ingredients, or add ingredients to one it already knows.",
            {
                vol.Required("dish"): str,
                vol.Optional("ingredients"): [str],
                vol.Optional("usual_day"): str,
            },
            lambda ctx, args: api.learn_dish(
                ctx, args["dish"], args.get("ingredients", []), usual_day=args.get("usual_day")
            ),
        ),
        tool(
            "sort_list",
            "Reorder the open shopping list into the walking route of a store.",
            {vol.Optional("store"): str},
            lambda ctx, args: api.sort_list(ctx, args.get("store")),
        ),
        tool(
            "export_knowledge",
            "Return everything the integration knows — departments, stores, articles, "
            "dishes, the plan and the listing history — as a knowledge file.",
            {},
            lambda ctx, args: export_knowledge(ctx.store, ctx.today),
        ),
    ]


def _prompt(entry: MealPlanConfigEntry) -> str:
    """Describe the situation to the model, briefly and factually."""
    ctx_store = entry.runtime_data.store
    options = plan_options(entry)
    lines = [
        f"You are helping with the household meal plan and shopping list called {entry.title!r}.",
        "",
        "Rules that are not yours to bend:",
        "- Never write to the household's own calendars. You may read them.",
        "- An empty day in the menu is a normal, deliberate state. Do not fill every day.",
        "- Planning a dish does not add anything to the shopping list. Adding is a separate step.",
        "- Dish and article names are the household's own words. Use them exactly; do not translate them.",
        "",
        (
            f"The planning window starts on {options.week_start} and runs {options.menu_days} days, "
            f"rolling over on {options.rollover_day}."
        ),
        f"It knows {len(ctx_store.data.dishes)} dishes and {len(ctx_store.data.articles)} articles.",
    ]
    if entry.runtime_data.store_choice:
        lines.append(f"The store currently selected is {entry.runtime_data.store_choice}.")
    return "\n".join(lines)


class MealPlanLLMAPI(llm.API):
    """The LLM API for one configured meal plan."""

    def __init__(self, hass: HomeAssistant, entry: MealPlanConfigEntry) -> None:
        """Register an API for a meal plan."""
        super().__init__(hass=hass, id=f"{DOMAIN}-{entry.entry_id}", name=f"{entry.title} (Meal Plan)")
        self._entry = entry

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        """Return the tools and the prompt."""
        return llm.APIInstance(
            api=self,
            api_prompt=_prompt(self._entry),
            llm_context=llm_context,
            tools=_tools(self._entry),
        )


def async_get_tools(hass: HomeAssistant, entry: MealPlanConfigEntry) -> list[llm.Tool]:
    """Return the toolset, for callers that want the tools without the API wrapper."""
    del hass
    return _tools(entry)


def async_register_api(hass: HomeAssistant, entry: MealPlanConfigEntry) -> Callable[[], None]:
    """Register this meal plan as an LLM API and return the unregister callback."""
    return llm.async_register_api(hass, MealPlanLLMAPI(hass, entry))
