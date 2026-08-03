# SPDX-License-Identifier: GPL-3.0-or-later
"""The three to-do lists: this trip, next trip, and what is in the fridge."""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_UPDATED, ListName
from .entity import MealPlanEntity
from .models import ListItem
from .types import MealPlanConfigEntry

BASE_FEATURES = (
    TodoListEntityFeature.CREATE_TODO_ITEM
    | TodoListEntityFeature.DELETE_TODO_ITEM
    | TodoListEntityFeature.UPDATE_TODO_ITEM
    | TodoListEntityFeature.MOVE_TODO_ITEM
    | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MealPlanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the to-do lists."""
    async_add_entities(
        MealPlanTodoList(entry, list_name) for list_name in (ListName.SHOPPING, ListName.LATER, ListName.STOCK)
    )


class MealPlanTodoList(MealPlanEntity, TodoListEntity):
    """A to-do list backed by the integration's own store.

    Not `local_todo`: this list needs to reorder itself into the walking route
    of whichever store you picked, and it needs to remember which dish put an
    item there.
    """

    _attr_supported_features = BASE_FEATURES

    def __init__(self, entry: MealPlanConfigEntry, list_name: ListName) -> None:
        """Set up one list."""
        super().__init__(entry)
        self._list_name = list_name
        self._attr_translation_key = str(list_name)
        self._attr_unique_id = f"{entry.entry_id}_{list_name}"

    async def async_added_to_hass(self) -> None:
        """Start listening for changes made by the services."""
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        """Redraw after a service changed the underlying data."""
        self.async_write_ha_state()

    # ------------------------------------------------------------------ mapping

    def _description(self, item: ListItem) -> str | None:
        """Return what to show as the description.

        A note if there is one, otherwise the department label — so that the
        stock built-in to-do card is already useful before any custom card
        exists. `_note_from_description` reverses this exactly.
        """
        if item.note:
            return item.note
        label = self._store.department_label(item.department, self.hass.config.language)
        return label if item.department != "unknown" else None

    def _note_from_description(self, item: ListItem, description: str | None) -> str | None:
        """Turn an incoming description back into a note.

        If it is byte-for-byte the department label we put there ourselves, the
        user did not type a note; anything else is theirs.
        """
        if not description:
            return None
        if description == self._store.department_label(item.department, self.hass.config.language):
            return None
        return description

    def _to_todo_item(self, item: ListItem) -> TodoItem:
        """Render one stored item as a Home Assistant to-do item."""
        return TodoItem(
            uid=item.uid,
            summary=item.summary,
            status=TodoItemStatus.COMPLETED if item.completed else TodoItemStatus.NEEDS_ACTION,
            due=item.due,
            description=self._description(item),
        )

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the items, open ones first, in the order they are stored."""
        return [self._to_todo_item(item) for item in self._store.items(self._list_name)]

    # ------------------------------------------------------------------ writing

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item, without asking a single question about it."""
        summary = (item.summary or "").strip()
        if not summary:
            return
        self._store.add_item(
            self._list_name,
            summary,
            self._today,
            due=_as_date(item.due),
            note=item.description or None,
        )
        await self._async_persist()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update an item's summary, status, due date or description."""
        stored = self._store.find_item(self._list_name, item.uid or "")
        if stored is None:
            return
        if item.summary is not None:
            stored.summary = item.summary.strip()
        if item.status is not None:
            stored.completed = item.status == TodoItemStatus.COMPLETED
        stored.due = _as_date(item.due)
        stored.note = self._note_from_description(stored, item.description)
        await self._async_persist()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove items. Taking something off is as easy as putting it on."""
        self._store.remove_items(self._list_name, uids)
        await self._async_persist()

    async def async_move_todo_item(self, uid: str, previous_uid: str | None = None) -> None:
        """Move an item, so the list can be dragged into the order of the shop."""
        items = self._store.items(self._list_name)
        moving = next((item for item in items if item.uid == uid), None)
        if moving is None:
            return
        items.remove(moving)
        if previous_uid is None:
            items.insert(0, moving)
        else:
            after = next((index for index, item in enumerate(items) if item.uid == previous_uid), None)
            items.insert(len(items) if after is None else after + 1, moving)
        await self._async_persist()


def _as_date(value: date | datetime | None) -> date | None:
    """Reduce a due value to a plain date; times are meaningless for groceries."""
    if isinstance(value, datetime):
        return dt_util.as_local(value).date()
    return value


__all__ = ["DOMAIN", "MealPlanTodoList", "async_setup_entry"]
