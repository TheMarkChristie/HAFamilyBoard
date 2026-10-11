"""The board's sensors: today, the week, birthdays, the Events board and the next trip for the household, and a chores
sensor and a points sensor for each person. The cards read these; so can any template or automation."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, KIND_BIRTHDAYS, KIND_CHORES, KIND_EVENTS, KIND_LISTS, KIND_POINTS, KIND_TODAY, KIND_TRIP, KIND_WEEK, NAME
from .coordinator import FamilyBoardCoordinator
from .model import Person

BOARD_KINDS = {
    KIND_TODAY: ("Today", "mdi:calendar-today"),
    KIND_WEEK: ("Week ahead", "mdi:calendar-week"),
    KIND_BIRTHDAYS: ("Birthdays", "mdi:cake-variant"),
    KIND_EVENTS: ("Events board", "mdi:ticket-confirmation"),
    KIND_TRIP: ("Next trip", "mdi:airplane-takeoff"),
    KIND_LISTS: ("Lists", "mdi:format-list-checks"),
}
MODE_ICON = {"flight": "mdi:airplane-takeoff", "ferry": "mdi:ferry", "train": "mdi:train", "car": "mdi:car", "other": "mdi:bag-suitcase"}

# the lists are the board, not history: keep them out of the recorder
BIG = frozenset({"all_day", "columns", "everyone", "days", "upcoming", "today_birthdays", "events", "trips", "trip", "open",
                 "later", "done", "done_today", "people", "homes", "next", "lists"})


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator: FamilyBoardCoordinator = entry.runtime_data
    async_add_entities([BoardSensor(coordinator, kind) for kind in BOARD_KINDS])
    for person in coordinator.people:
        async_add_entities([ChoresSensor(coordinator, person), PointsSensor(coordinator, person)],
                           config_subentry_id=person.subentry)


def _board_device(coordinator: FamilyBoardCoordinator) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, coordinator.entry.entry_id)}, name=f"{NAME}: {coordinator.household}",
                      manufacturer=NAME, model="Board", entry_type=DeviceEntryType.SERVICE)


class _Base(CoordinatorEntity[FamilyBoardCoordinator], SensorEntity):
    _attr_has_entity_name = False
    _unrecorded_attributes = BIG

    def _meta(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("meta") or {}

    def _common(self, kind: str) -> dict[str, Any]:
        meta = self._meta()
        return {"family_board": kind, "household": meta.get("household"), "homes": meta.get("homes"),
                "people": meta.get("people"), "date": meta.get("today"), "tz": meta.get("tz"), "stale": meta.get("stale", False),
                "updated": meta.get("now")}


class BoardSensor(_Base):
    """One of the household-wide sensors."""

    def __init__(self, coordinator: FamilyBoardCoordinator, kind: str) -> None:
        super().__init__(coordinator)
        self.kind = kind
        label, icon = BOARD_KINDS[kind]
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{kind}"
        self._attr_name = f"{NAME} {label}"
        self._attr_suggested_object_id = f"family_board_{kind}"
        self.entity_id = f"sensor.family_board_{kind}"
        self._attr_icon = icon
        self._attr_device_info = _board_device(coordinator)

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data or {}
        if self.kind == KIND_TODAY:
            return (data.get("today") or {}).get("count", 0)
        if self.kind == KIND_WEEK:
            return sum(len(d["events"]) for d in data.get("week") or [])
        if self.kind == KIND_BIRTHDAYS:
            nxt = (data.get("birthdays") or {}).get("next")
            return nxt["days"] if nxt else None
        if self.kind == KIND_EVENTS:
            return len(data.get("events") or [])
        if self.kind == KIND_LISTS:
            return sum(int(l.get("open_count", 0)) for l in data.get("lists") or [])
        nxt = (data.get("trips") or {}).get("next")
        return nxt["days"] if nxt else None

    @property
    def icon(self) -> str:
        if self.kind == KIND_TRIP:
            nxt = ((self.coordinator.data or {}).get("trips") or {}).get("next")
            if nxt:
                return MODE_ICON.get(nxt.get("mode"), MODE_ICON["other"])
        return BOARD_KINDS[self.kind][1]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        attrs = self._common(self.kind)
        if self.kind == KIND_TODAY:
            today = data.get("today") or {}
            attrs.update({"all_day": today.get("all_day", []), "columns": today.get("columns", []),
                          "everyone": today.get("household", []), "count": today.get("count", 0)})
        elif self.kind == KIND_WEEK:
            attrs.update({"days": data.get("week") or [], "days_ahead": self.coordinator._setting("days_ahead", 7)})
        elif self.kind == KIND_BIRTHDAYS:
            b = data.get("birthdays") or {}
            attrs.update({"next": b.get("next"), "today_birthdays": b.get("today", []), "upcoming": b.get("upcoming", []),
                          "count": b.get("count", 0)})
        elif self.kind == KIND_EVENTS:
            attrs.update({"events": data.get("events") or [], "count": len(data.get("events") or [])})
        elif self.kind == KIND_LISTS:
            lists = data.get("lists") or []
            attrs.update({"lists": lists, "count": sum(int(l.get("open_count", 0)) for l in lists)})
        else:
            t = data.get("trips") or {}
            attrs.update({"trip": t.get("next"), "trips": t.get("trips", []), "count": t.get("count", 0)})
        return attrs


class _PersonBase(_Base):
    def __init__(self, coordinator: FamilyBoardCoordinator, person: Person, kind: str, label: str, icon: str) -> None:
        super().__init__(coordinator)
        self.person_id = person.id
        self.kind = kind
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{kind}_{person.id}"
        self._attr_name = f"{NAME} {label} {person.name}"
        self._attr_suggested_object_id = f"family_board_{kind}_{person.id}"
        self.entity_id = f"sensor.family_board_{kind}_{person.id}"
        self._attr_icon = icon
        # no via_device: Home Assistant 2026.10 deprecates the identifier form, and the hierarchy adds nothing here
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}:{person.id}")}, name=person.name, manufacturer=NAME,
            model=person.role.capitalize(), entry_type=DeviceEntryType.SERVICE)

    def _mine(self) -> dict[str, Any]:
        return ((self.coordinator.data or {}).get("chores") or {}).get(self.person_id) or {}

    def _person(self) -> dict[str, Any] | None:
        return next((p for p in self._meta().get("people") or [] if p.get("id") == self.person_id), None)


class ChoresSensor(_PersonBase):
    """What this person still has to do today."""

    def __init__(self, coordinator: FamilyBoardCoordinator, person: Person) -> None:
        super().__init__(coordinator, person, KIND_CHORES, "Chores", "mdi:broom")

    @property
    def native_value(self) -> int:
        return int(self._mine().get("open_count", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mine = self._mine()
        attrs = self._common(KIND_CHORES)
        attrs.update({"person": self._person(), "todo_entity": mine.get("todo_entity"), "open": mine.get("open", []),
                      "later": mine.get("later", []), "done": mine.get("done", []), "done_today": mine.get("done_today", []),
                      "open_count": mine.get("open_count", 0), "open_points": mine.get("open_points", 0),
                      "points_today": mine.get("points_today", 0), "points_week": mine.get("points_week", 0),
                      "done_week": mine.get("done_week", 0), "week_start": mine.get("week_start")})
        return attrs


class PointsSensor(_PersonBase):
    """This person's points this week."""

    _attr_native_unit_of_measurement = "points"

    def __init__(self, coordinator: FamilyBoardCoordinator, person: Person) -> None:
        super().__init__(coordinator, person, KIND_POINTS, "Points", "mdi:medal")

    @property
    def native_value(self) -> int:
        return int(self._mine().get("points_week", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mine = self._mine()
        attrs = self._common(KIND_POINTS)
        attrs.update({"person": self._person(), "points_today": mine.get("points_today", 0), "done_week": mine.get("done_week", 0),
                      "done_today": mine.get("done_today", []), "week_start": mine.get("week_start")})
        return attrs
