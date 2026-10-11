"""One coordinator per signed-in Microsoft account: keeps the tracked calendars' coming events and the tracked To Do
lists' items current, renews the tokens and stores them back on the entry, and asks for a fresh sign-in when Microsoft
will no longer refresh them."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEvent
from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ACCOUNT_DAYS_AHEAD,
    CONF_ACCOUNT,
    CONF_ACCOUNT_NAME,
    CONF_ACCOUNT_SCAN,
    CONF_CALENDAR_IDS,
    CONF_CLIENT_ID,
    CONF_LIST_IDS,
    CONF_TENANT,
    CONF_TOKENS,
    DEFAULT_ACCOUNT_SCAN,
    DEFAULT_CLIENT_ID,
    DEFAULT_TENANT,
    DOMAIN,
)
from .graph import GraphAuthError, GraphClient, GraphError, Tokens, parse_event, parse_task

_LOGGER = logging.getLogger(__name__)
LIVE_CACHE_SECONDS = 120     # a calendar panel asking for the same window twice in two minutes gets the same answer


def to_calendar_event(ev: dict[str, Any]) -> CalendarEvent:
    return CalendarEvent(start=ev["start"], end=ev["end"], summary=ev["summary"], description=ev.get("description"),
                         location=ev.get("location"), uid=ev.get("uid") or None)


def to_todo_item(task: dict[str, Any]) -> TodoItem:
    return TodoItem(summary=task["summary"], uid=task["uid"],
                    status=TodoItemStatus.COMPLETED if task["status"] == "completed" else TodoItemStatus.NEEDS_ACTION,
                    due=task.get("due"), description=task.get("description"))


class AccountCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """The account's calendars and lists, read on a schedule."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}",
                         update_interval=timedelta(minutes=int(entry.options.get(CONF_ACCOUNT_SCAN, DEFAULT_ACCOUNT_SCAN))))
        self.entry = entry
        self.client = GraphClient(async_get_clientsession(hass), str(entry.data.get(CONF_CLIENT_ID) or DEFAULT_CLIENT_ID),
                                  Tokens.from_dict(entry.data.get(CONF_TOKENS) or {}), str(entry.data.get(CONF_TENANT) or DEFAULT_TENANT),
                                  on_tokens=self._store_tokens)
        self._live: dict[tuple[str, str, str], tuple[float, list[CalendarEvent]]] = {}
        self.options_seen = dict(entry.options)

    @property
    def account(self) -> dict[str, Any]:
        return dict(self.entry.data.get(CONF_ACCOUNT) or {})

    @property
    def account_name(self) -> str:
        return str(self.entry.options.get(CONF_ACCOUNT_NAME) or self.entry.data.get(CONF_ACCOUNT_NAME) or self.entry.title)

    @property
    def calendar_ids(self) -> list[str]:
        return [str(c) for c in self.entry.options.get(CONF_CALENDAR_IDS) or []]

    @property
    def list_ids(self) -> list[str]:
        return [str(c) for c in self.entry.options.get(CONF_LIST_IDS) or []]

    def _store_tokens(self, tokens: Tokens) -> None:
        """Microsoft rotates refresh tokens: whatever came back is what works next time, so it goes on the entry at once."""
        self.hass.config_entries.async_update_entry(self.entry, data={**self.entry.data, CONF_TOKENS: tokens.to_dict()})

    async def _async_update_data(self) -> dict[str, Any]:
        tz: ZoneInfo = dt_util.get_default_time_zone()  # type: ignore[assignment]
        now = dt_util.now()
        start = now - timedelta(days=1)
        end = now + timedelta(days=ACCOUNT_DAYS_AHEAD)
        data: dict[str, Any] = {"calendars": {}, "lists": {}, "updated": now.isoformat()}
        try:
            names = {c["id"]: c for c in await self.client.calendars() if c.get("id")}
            for cal_id in self.calendar_ids:
                meta = names.get(cal_id) or {"id": cal_id, "name": (self.data or {}).get("calendars", {}).get(cal_id, {}).get("name") or "Calendar"}
                raws = await self.client.calendar_view(cal_id, start, end, str(tz))
                events = [to_calendar_event(ev) for ev in (parse_event(r, tz) for r in raws) if ev]
                events.sort(key=lambda e: dt_util.start_of_local_day(e.start) if not isinstance(e.start, datetime) else e.start)
                data["calendars"][cal_id] = {"name": meta.get("name") or "Calendar", "default": bool(meta.get("isDefaultCalendar")),
                                             "events": events}
            if self.list_ids:
                lists = {lst["id"]: lst for lst in await self.client.todo_lists() if lst.get("id")}
                for list_id in self.list_ids:
                    meta = lists.get(list_id) or {"displayName": (self.data or {}).get("lists", {}).get(list_id, {}).get("name") or "List"}
                    raws = await self.client.tasks(list_id)
                    tasks = [t for t in (parse_task(r, tz, now) for r in raws) if t]
                    data["lists"][list_id] = {"name": meta.get("displayName") or "List", "items": [to_todo_item(t) for t in tasks],
                                              "completed": {t["uid"]: t["completed"] for t in tasks if t.get("completed")},
                                              "recurring": [t["uid"] for t in tasks if t.get("recurring")]}
        except GraphAuthError as err:
            raise ConfigEntryAuthFailed(f"{self.entry.title}: sign in again ({err})") from err
        except GraphError as err:
            raise UpdateFailed(f"{self.entry.title}: {err}") from err
        return data

    async def async_events(self, cal_id: str, start: datetime, end: datetime) -> list[CalendarEvent]:
        """A calendar's events for any window, straight from Graph, with a short memory for repeated asks."""
        key = (cal_id, start.isoformat(), end.isoformat())
        hit = self._live.get(key)
        if hit and time.monotonic() - hit[0] < LIVE_CACHE_SECONDS:
            return hit[1]
        tz: ZoneInfo = dt_util.get_default_time_zone()  # type: ignore[assignment]
        try:
            raws = await self.client.calendar_view(cal_id, start, end, str(tz))
        except GraphAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GraphError as err:
            raise UpdateFailed(str(err)) from err
        events = [to_calendar_event(ev) for ev in (parse_event(r, tz) for r in raws) if ev]
        if len(self._live) > 64:
            self._live.clear()
        self._live[key] = (time.monotonic(), events)
        return events
