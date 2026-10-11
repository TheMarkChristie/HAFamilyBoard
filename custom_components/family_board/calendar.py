"""A calendar entity per tracked Outlook calendar of a signed-in Microsoft account."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

from .account import AccountCoordinator
from .const import DOMAIN, NAME


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator: AccountCoordinator = entry.runtime_data
    async_add_entities([GraphCalendar(coordinator, cal_id) for cal_id in coordinator.calendar_ids])


def account_device(coordinator: AccountCoordinator) -> DeviceInfo:
    account = coordinator.account
    upn = str(account.get("upn") or "")
    return DeviceInfo(identifiers={(DOMAIN, f"account:{account.get('id') or coordinator.entry.entry_id}")},
                      name=coordinator.account_name, manufacturer="Microsoft",
                      model="Outlook.com" if upn.lower().endswith(("@hotmail.com", "@outlook.com", "@live.com", "@live.no", "@hotmail.no")) else "Microsoft 365",
                      entry_type=DeviceEntryType.SERVICE)


class GraphCalendar(CoordinatorEntity[AccountCoordinator], CalendarEntity):
    """One Outlook calendar, read-only."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: AccountCoordinator, cal_id: str) -> None:
        super().__init__(coordinator)
        self.cal_id = cal_id
        meta = (coordinator.data or {}).get("calendars", {}).get(cal_id) or {}
        calendar_name = str(meta.get("name") or "Calendar")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{cal_id}"
        self._attr_name = f"{coordinator.account_name} {calendar_name}"
        object_id = f"{slugify(coordinator.account_name)}_{slugify(calendar_name)}"
        self._attr_suggested_object_id = object_id
        self.entity_id = f"calendar.{object_id}"
        self._attr_device_info = account_device(coordinator)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # the id the registry settled on, so the board can name this calendar on tagged events
        self.coordinator.entity_ids[self.cal_id] = self.entity_id

    def _slice(self) -> dict:
        return (self.coordinator.data or {}).get("calendars", {}).get(self.cal_id) or {}

    @property
    def event(self) -> CalendarEvent | None:
        """The event on now, else the next one."""
        now = dt_util.now()
        today = now.date()
        best: CalendarEvent | None = None
        for ev in self._slice().get("events") or []:
            if isinstance(ev.end, datetime):
                if ev.end <= now:
                    continue
            elif ev.end <= today:
                continue
            best = ev
            break
        return best

    @property
    def extra_state_attributes(self) -> dict:
        return {"calendar_name": self._slice().get("name"), "account": self.coordinator.account_name, "integration": NAME}

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        return await self.coordinator.async_events(self.cal_id, start_date, end_date)
