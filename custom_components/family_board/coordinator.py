"""One coordinator for the whole board: it reads the household's calendars and to-do lists through Home Assistant's own
calendar.get_events and todo.get_items actions, so any provider works (Microsoft 365, Google, CalDAV, a local calendar),
and keeps the chores ledger that the scoreboards are built from."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util, slugify

from .const import (
    BIRTHDAY_DAYS,
    CONF_BIRTHDAY,
    CONF_BIRTHDAY_CALENDARS,
    CONF_BOARD_DAYS,
    CONF_CALENDARS,
    CONF_CHORES,
    CONF_COLOUR,
    CONF_COUNT_VANISHED,
    CONF_DAYS_AHEAD,
    CONF_DEFAULT_POINTS,
    CONF_EVENTS_CALENDARS,
    CONF_EVENTS_TAGS,
    CONF_LISTS,
    NAME,
    CONF_KIND,
    ENTRY_MICROSOFT,
    CONF_HOME_A_NAME,
    CONF_HOME_A_TZ,
    CONF_HOME_B_NAME,
    CONF_HOME_B_TZ,
    CONF_HOUSEHOLD,
    CONF_HOUSEHOLD_CALENDARS,
    CONF_NAME,
    CONF_ROLE,
    CONF_SCAN_MINUTES,
    CONF_SHORT_NAME,
    CONF_TRIP_DAYS,
    CONF_TRIP_PATTERN,
    CONF_TRIPS_CALENDARS,
    DEFAULT_BOARD_DAYS,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_HOME_A,
    DEFAULT_HOME_B,
    DEFAULT_POINTS,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_TRIP_DAYS,
    DOMAIN,
    LEDGER_KEEP_DAYS,
    PALETTE,
    STORAGE_VERSION,
    SUBENTRY_BIRTHDAY,
    SUBENTRY_PERSON,
    TRIP_PATTERN_DEFAULT,
    UPCOMING_BIRTHDAYS,
)
from .model import (
    Item,
    Occurrence,
    Person,
    assign_people,
    birthdays,
    chores_today,
    list_view,
    dedupe,
    events_board,
    ledger_update,
    parse_events,
    parse_items,
    points_summary,
    prune_ledger,
    today_board,
    trips,
    upcoming,
)

_LOGGER = logging.getLogger(__name__)
CHORES_LIST = re.compile(r"\b(chores?|husarbeid|oppgaver)\b", re.I)   # a list named like this is somebody's chores, not a list

SLOW_EVERY = timedelta(minutes=60)   # the long look-aheads (trips, the Events board, birthdays) are re-read this often
RETRY_MINUTES = 2


def _zone(name: str, fallback: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or fallback)
    except Exception:  # noqa: BLE001  (an unknown zone name must not take the board down)
        return ZoneInfo(fallback)


class FamilyBoardCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keeps the board current."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}",
                         update_interval=timedelta(minutes=int(entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES))))
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.ledger: list[dict[str, Any]] = []
        self._saved: dict[str, Any] | None = None
        self._last_items: dict[str, list[Item]] = {}
        self._slow_at: datetime | None = None
        self._slow: dict[str, list[Occurrence]] = {"trips": [], "events": [], "birthdays": []}
        self._main: list[Occurrence] = []
        self._unwatch: callable | None = None
        self._watching: list[str] = []

    # ---- settings ---------------------------------------------------------------------------------------------------

    def _setting(self, key: str, default: Any) -> Any:
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    def _list(self, key: str) -> list[str]:
        value = self._setting(key, [])
        if isinstance(value, str):
            return [value] if value else []
        return [str(v) for v in value or []]

    @property
    def household(self) -> str:
        return str(self._setting(CONF_HOUSEHOLD, "") or self.entry.title or "Family")

    @property
    def homes(self) -> list[dict[str, str]]:
        return [{"name": str(self._setting(CONF_HOME_A_NAME, DEFAULT_HOME_A[0])), "tz": str(self._setting(CONF_HOME_A_TZ, DEFAULT_HOME_A[1]))},
                {"name": str(self._setting(CONF_HOME_B_NAME, DEFAULT_HOME_B[0])), "tz": str(self._setting(CONF_HOME_B_TZ, DEFAULT_HOME_B[1]))}]

    @property
    def people(self) -> list[Person]:
        """The person subentries, in the order they were added, with a colour each."""
        out: list[Person] = []
        for index, sub in enumerate(s for s in self.entry.subentries.values() if s.subentry_type == SUBENTRY_PERSON):
            data = sub.data
            raw_birthday = data.get(CONF_BIRTHDAY)
            try:
                birthday = date.fromisoformat(str(raw_birthday)) if raw_birthday else None
            except ValueError:
                birthday = None
            name = str(data.get(CONF_NAME) or sub.title)
            out.append(Person(id=slugify(name), name=name, short=str(data.get(CONF_SHORT_NAME) or ""),
                              colour=str(data.get(CONF_COLOUR) or PALETTE[index % len(PALETTE)]),
                              role=str(data.get(CONF_ROLE) or "adult"), calendars=list(data.get(CONF_CALENDARS) or []),
                              chores=data.get(CONF_CHORES) or None, birthday=birthday, subentry=sub.subentry_id))
        return out

    @property
    def contacts(self) -> list[tuple[str, date]]:
        out = []
        for sub in self.entry.subentries.values():
            if sub.subentry_type != SUBENTRY_BIRTHDAY:
                continue
            try:
                out.append((str(sub.data.get(CONF_NAME) or sub.title), date.fromisoformat(str(sub.data.get(CONF_BIRTHDAY)))))
            except (TypeError, ValueError):
                continue
        return out

    @property
    def watched(self) -> list[str]:
        """Every entity the board reads; a change on any of them is a reason to read again soon."""
        ids: list[str] = []
        for key in (CONF_HOUSEHOLD_CALENDARS, CONF_BIRTHDAY_CALENDARS, CONF_EVENTS_CALENDARS, CONF_TRIPS_CALENDARS):
            ids += self._list(key)
        for person in self.people:
            ids += person.calendars
            if person.chores:
                ids.append(person.chores)
        ids += self.list_entities
        return sorted(set(ids))

    @property
    def list_entities(self) -> list[str]:
        """The Lists board: the chosen to-do lists, else every Family Board list that is nobody's chores."""
        chosen = self._list(CONF_LISTS)
        if chosen:
            return chosen
        chores = {p.chores for p in self.people if p.chores}
        out: list[str] = []
        for state in self.hass.states.async_all("todo"):
            if state.attributes.get("integration") != NAME or state.entity_id in chores:
                continue
            if CHORES_LIST.search(str(state.attributes.get("list_name") or state.name or "")):
                continue
            out.append(state.entity_id)
        return sorted(out)

    # ---- persistence and watching -------------------------------------------------------------------------------------

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict) and isinstance(data.get("ledger"), list):
            self.ledger = [e for e in data["ledger"] if isinstance(e, dict)]
            self._saved = data

    async def _async_save(self) -> None:
        data = {"ledger": self.ledger}
        if data != self._saved:
            await self._store.async_save(data)
            self._saved = {"ledger": list(self.ledger)}

    async def async_remove_store(self) -> None:
        await self._store.async_remove()

    @callback
    def _rearm(self) -> None:
        """Watch the current set of entities: at start, and again after a read in case a list has come or gone."""
        watched = self.watched
        if watched == self._watching:
            return
        if self._unwatch:
            self._unwatch()
            self._unwatch = None
        self._watching = watched
        if not watched:
            return

        @callback
        def _changed(_event: Event[EventStateChangedData]) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        self._unwatch = async_track_state_change_event(self.hass, watched, _changed)

    @callback
    def async_watch(self) -> callable:
        """Refresh soon after any watched calendar or list changes state (a tick, a new event, a sync)."""
        self._rearm()

        def _stop() -> None:
            if self._unwatch:
                self._unwatch()
                self._unwatch = None
            self._watching = []

        return _stop

    # ---- reading ----------------------------------------------------------------------------------------------------

    def _present(self, ids: list[str]) -> list[str]:
        return [e for e in ids if self.hass.states.get(e) is not None]

    async def _events(self, ids: list[str], start: datetime, end: datetime) -> dict[str, Any] | None:
        ids = self._present(ids)
        if not ids or not self.hass.services.has_service("calendar", "get_events"):
            return {}
        try:
            return await self.hass.services.async_call(
                "calendar", "get_events", {"start_date_time": start, "end_date_time": end},
                target={"entity_id": ids}, blocking=True, return_response=True) or {}
        except HomeAssistantError as err:
            _LOGGER.warning("%s: could not read %s: %s", self.name, ", ".join(ids), err)
            return None

    async def _items(self, entity_id: str, tz: ZoneInfo) -> list[Item] | None:
        if self.hass.states.get(entity_id) is None or not self.hass.services.has_service("todo", "get_items"):
            return None
        try:
            response = await self.hass.services.async_call(
                "todo", "get_items", {"status": ["needs_action", "completed"]},
                target={"entity_id": entity_id}, blocking=True, return_response=True) or {}
        except HomeAssistantError as err:
            _LOGGER.warning("%s: could not read %s: %s", self.name, entity_id, err)
            return None
        return parse_items(response.get(entity_id), tz)

    async def _tagged(self, start: datetime, end: datetime, tags: list[str], tz: ZoneInfo) -> list[Occurrence]:
        """Tagged events from every signed-in Microsoft account on this installation."""
        out: list[Occurrence] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            account = getattr(entry, "runtime_data", None)
            if entry.data.get(CONF_KIND) != ENTRY_MICROSOFT or account is None or not hasattr(account, "async_tagged"):
                continue
            for ev in await account.async_tagged(start, end, tags):
                s, e = ev["start"], ev["end"]
                if not isinstance(s, datetime):
                    s = datetime.combine(s, datetime.min.time(), tzinfo=tz)
                    e = datetime.combine(e, datetime.min.time(), tzinfo=tz)
                out.append(Occurrence(summary=ev["summary"], start=s, end=e, all_day=bool(ev.get("all_day")), calendar=ev["calendar"],
                                      location=ev.get("location"), description=ev.get("description")))
        return out

    async def _async_update_data(self) -> dict[str, Any]:
        tz: ZoneInfo = dt_util.get_default_time_zone()  # type: ignore[assignment]
        now = dt_util.now()
        today = now.date()
        people = self.people
        homes = self.homes
        tz_a, tz_b = _zone(homes[0]["tz"], DEFAULT_HOME_A[1]), _zone(homes[1]["tz"], DEFAULT_HOME_B[1])
        days_ahead = int(self._setting(CONF_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))
        board_days = int(self._setting(CONF_BOARD_DAYS, DEFAULT_BOARD_DAYS))
        trip_days = int(self._setting(CONF_TRIP_DAYS, DEFAULT_TRIP_DAYS))
        default_points = int(self._setting(CONF_DEFAULT_POINTS, DEFAULT_POINTS))
        count_vanished = bool(self._setting(CONF_COUNT_VANISHED, False))
        pattern = str(self._setting(CONF_TRIP_PATTERN, TRIP_PATTERN_DEFAULT) or "")
        failed = False

        person_calendars = sorted({c for p in people for c in p.calendars})
        household_calendars = self._list(CONF_HOUSEHOLD_CALENDARS)
        day_start = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=tz)

        # the week: everyone's calendars and the household's, yesterday to the days ahead
        response = await self._events(person_calendars + household_calendars, day_start, day_start + timedelta(days=days_ahead + 2))
        if response is None:
            failed = True
        else:
            occs = parse_events(response, tz)
            assign_people(occs, people)
            self._main = dedupe(occs)

        # the long looks ahead, once an hour: trips on every calendar, the Events board, the birthdays calendars
        if self._slow_at is None or now - self._slow_at >= SLOW_EVERY:
            slow_ok = True
            trip_ids = sorted(set(self._list(CONF_TRIPS_CALENDARS) + (person_calendars + household_calendars if pattern else [])))
            response = await self._events(trip_ids, day_start, day_start + timedelta(days=trip_days + 1))
            if response is None:
                slow_ok = False
            else:
                occs = parse_events(response, tz)
                assign_people(occs, people)
                self._slow["trips"] = dedupe(occs)
            response = await self._events(self._list(CONF_EVENTS_CALENDARS), day_start, day_start + timedelta(days=board_days + 1))
            if response is None:
                slow_ok = False
            else:
                board_occs = parse_events(response, tz)
                # and anything on a tracked Outlook calendar wearing one of the board's tags (Concert, Sports, ...)
                tags = [str(t) for t in self._list(CONF_EVENTS_TAGS)]
                if tags:
                    board_occs += await self._tagged(day_start, day_start + timedelta(days=board_days + 1), tags, tz)
                assign_people(board_occs, people)
                self._slow["events"] = dedupe(board_occs)
            response = await self._events(self._list(CONF_BIRTHDAY_CALENDARS), day_start, day_start + timedelta(days=BIRTHDAY_DAYS + 1))
            if response is None:
                slow_ok = False
            else:
                self._slow["birthdays"] = dedupe(parse_events(response, tz))
            if slow_ok:
                self._slow_at = now
            else:
                failed = True

        # chores: each person's list, and the ledger of what was ticked since the last read
        chores: dict[str, dict[str, Any]] = {}
        added = []
        for person in people:
            if not person.chores:
                continue
            items = await self._items(person.chores, tz)
            if items is None:
                failed = True
                items = self._last_items.get(person.chores)
                if items is None:
                    continue
            else:
                added += ledger_update(self.ledger, person.id, self._last_items.get(person.chores), items, now,
                                       default_points, count_vanished)
                self._last_items[person.chores] = items
            view = chores_today(items, today, default_points)
            view.update({"person": person.id, "todo_entity": person.chores})
            chores[person.id] = view
        if added:
            self.ledger += added
        pruned = prune_ledger(self.ledger, today, LEDGER_KEEP_DAYS)
        if len(pruned) != len(self.ledger) or added:
            self.ledger = pruned
            await self._async_save()
        for person in people:
            score = points_summary(self.ledger, person.id, today)
            chores.setdefault(person.id, {"person": person.id, "todo_entity": None, "open": [], "later": [], "done": [],
                                          "open_count": 0, "open_points": 0}).update(score)

        # the Lists board: shopping, packing and to-do lists, open items first
        lists_view: list[dict[str, Any]] = []
        for entity_id in self.list_entities:
            items = await self._items(entity_id, tz)
            if items is None:
                failed = True
                continue
            state = self.hass.states.get(entity_id)
            name = str((state.attributes.get("list_name") if state else None) or (state.name if state else None) or entity_id)
            lists_view.append(list_view(entity_id, name, items))

        if failed and self.data is None and not self._main and not any(self._slow.values()):
            raise UpdateFailed("none of the calendars or lists could be read")

        trip_calendars = set(self._list(CONF_TRIPS_CALENDARS))
        data = {
            "meta": {"household": self.household, "homes": homes, "tz": str(tz), "today": today.isoformat(),
                     "now": now.isoformat(), "stale": failed, "people": [p.summary() for p in people],
                     "contacts": len(self.contacts)},
            "today": today_board(self._main, people, today, tz),
            "week": upcoming(self._main, today, days_ahead, tz),
            "birthdays": birthdays(people, self.contacts, self._slow["birthdays"], today, tz, UPCOMING_BIRTHDAYS),
            "events": events_board(self._slow["events"], today, board_days, tz),
            "trips": trips(self._slow["trips"] + [o for o in self._main if o.calendar in trip_calendars], trip_calendars,
                           pattern or None, now, tz, tz_a, tz_b, trip_days),
            "chores": chores,
            "lists": lists_view,
        }
        self.update_interval = timedelta(minutes=RETRY_MINUTES if failed else int(self._setting(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)))
        self._rearm()
        return data
