"""A to-do entity per tracked Microsoft To Do list of a signed-in account. Ticks, adds, edits and deletions made in
Home Assistant go straight to To Do, so the phone app and the kitchen tablet always agree."""
from __future__ import annotations

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .account import AccountCoordinator
from .calendar import account_device
from .const import NAME
from .graph import GraphError, task_body


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator: AccountCoordinator = entry.runtime_data
    async_add_entities([GraphTodoList(coordinator, list_id) for list_id in coordinator.list_ids])


class GraphTodoList(CoordinatorEntity[AccountCoordinator], TodoListEntity):
    """One Microsoft To Do list."""

    _attr_has_entity_name = False
    _attr_supported_features = (TodoListEntityFeature.CREATE_TODO_ITEM | TodoListEntityFeature.UPDATE_TODO_ITEM
                                | TodoListEntityFeature.DELETE_TODO_ITEM | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
                                | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)

    def __init__(self, coordinator: AccountCoordinator, list_id: str) -> None:
        super().__init__(coordinator)
        self.list_id = list_id
        list_name = str(self._slice().get("name") or "List")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{list_id}"
        self._attr_name = f"{coordinator.account_name} {list_name}"
        object_id = f"{slugify(coordinator.account_name)}_{slugify(list_name)}"
        self._attr_suggested_object_id = object_id
        self.entity_id = f"todo.{object_id}"
        self._attr_device_info = account_device(coordinator)
        self._attr_todo_items = list(self._slice().get("items") or [])

    def _slice(self) -> dict:
        return (self.coordinator.data or {}).get("lists", {}).get(self.list_id) or {}

    def _handle_coordinator_update(self) -> None:
        # the core pattern: the items land on the attribute so the to-do panel's live subscriptions see every change
        self._attr_todo_items = list(self._slice().get("items") or [])
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict:
        s = self._slice()
        return {"list_name": s.get("name"), "account": self.coordinator.account_name, "integration": NAME,
                "completed_at": s.get("completed") or {}, "recurring": s.get("recurring") or []}

    async def _call(self, coro) -> None:
        try:
            await coro
        except GraphError as err:
            raise HomeAssistantError(f"Microsoft To Do: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_create_todo_item(self, item: TodoItem) -> None:
        body = task_body(summary=item.summary or "(untitled)", status="completed" if item.status == TodoItemStatus.COMPLETED else "needs_action",
                         due=item.due, description=item.description)
        await self._call(self.coordinator.client.create_task(self.list_id, body))

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if not item.uid:
            raise HomeAssistantError("Microsoft To Do: the item has no id")
        body = task_body(summary=item.summary, status=None if item.status is None else ("completed" if item.status == TodoItemStatus.COMPLETED else "needs_action"),
                         due=item.due, description=item.description)
        await self._call(self.coordinator.client.update_task(self.list_id, item.uid, body))

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        async def _delete_all() -> None:
            for uid in uids:
                await self.coordinator.client.delete_task(self.list_id, uid)
        await self._call(_delete_all())
