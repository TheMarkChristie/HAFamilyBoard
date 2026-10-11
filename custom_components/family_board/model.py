"""The board as pure functions: calendar events and to-do items in, the sensors' attributes out.

Everything here is plain Python so it can be tested without Home Assistant. The coordinator feeds it the responses
of `calendar.get_events` and `todo.get_items`, exactly as Home Assistant returns them, and the household's people.

Two rules carried over from FamilyHub, because they are the ones calendar apps get wrong:
- an all-day event is a floating date, never an instant: a birthday is the 3rd in Perth and the 3rd in Oslo;
- a timed event is one instant shown on two clocks: 14:05 out of Edinburgh is 15:05 on the arrivals board in Oslo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo


FLIGHT_CODE = re.compile(r"(?<![A-Z0-9])([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?(\d{2,4})(?![A-Z0-9])")
POINTS_PATTERNS = [
    re.compile(r"\((\d{1,3})\s*(?:pts?|points?|poeng|p)\)", re.I),
    re.compile(r"\[(\d{1,3})\]"),
    re.compile(r"\b(\d{1,3})\s*(?:pts?|points?|poeng)\b", re.I),
]
BIRTHDAY_NAME = [
    re.compile(r"^(.*?)(?:'s|’s|s|\s+sin|\s+si|\s+sitt)\s+(?:birthday|bursdag|f[øo]dselsdag)\b", re.I),
    re.compile(r"^(?:birthday|bursdag|f[øo]dselsdag)\s*[:\-–]\s*(.+)$", re.I),
    re.compile(r"^(.+?)\s+(?:birthday|bursdag|f[øo]dselsdag)$", re.I),
]
YEAR = re.compile(r"\b(19\d\d|20\d\d)\b")
ROUTE_SPLIT = re.compile(r"\s+(?:→|->|-->|to|til|-|–)\s+", re.I)
DESTINATION = re.compile(r"\b(?:to|til)\s+([A-Za-zÀ-ÿ][\w\sÀ-ÿ'.-]*?)(?=\s*[(\[,;]|\s+(?:on|den|\d)|$)", re.I)
MODE_WORDS = [
    ("flight", re.compile(r"\b(flight|fly|flyr|plane|airport|flyplass)\b", re.I)),
    ("ferry", re.compile(r"\b(ferry|ferje|ferge|crossing|sailing)\b", re.I)),
    ("train", re.compile(r"\b(train|tog|rail|eurostar|station)\b", re.I)),
    ("car", re.compile(r"\b(drive|driving|car|bil|kjøre)\b", re.I)),
]


@dataclass
class Person:
    id: str
    name: str
    short: str = ""
    colour: str = "#4f8cff"
    role: str = "adult"
    calendars: list[str] = field(default_factory=list)
    chores: str | None = None
    birthday: date | None = None
    subentry: str | None = None   # the config subentry this person came from

    @property
    def display(self) -> str:
        return self.short or self.name

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "short": self.display, "colour": self.colour, "role": self.role,
                "chores_entity": self.chores}


@dataclass
class Occurrence:
    """One calendar event as a calendar.get_events response gives it, normalised."""

    summary: str
    start: datetime               # aware; for an all-day event, midnight of its first day in the board's zone
    end: datetime                 # aware; for an all-day event, midnight after its last day
    all_day: bool
    calendar: str
    location: str | None = None
    description: str | None = None
    status: str | None = None
    person_ids: list[str] = field(default_factory=list)

    def date_in(self, tz: ZoneInfo) -> date:
        return self.start.astimezone(tz).date()

    def days_in(self, tz: ZoneInfo) -> list[date]:
        """Every calendar day the event touches, read in the board's zone."""
        first = self.start.astimezone(tz).date()
        last_instant = self.end.astimezone(tz)
        last = (last_instant - timedelta(microseconds=1)).date() if self.end > self.start else first
        if not self.all_day and last_instant.time() == time(0) and last_instant.date() > first and self.end > self.start:
            last = (last_instant - timedelta(days=1)).date()
        if last < first:
            last = first
        return [first + timedelta(days=i) for i in range((last - first).days + 1)]

    def present(self) -> dict[str, Any]:
        return {"summary": self.summary, "start": self.start.isoformat(), "end": self.end.isoformat(),
                "all_day": self.all_day, "location": self.location, "description": self.description,
                "people": list(self.person_ids), "calendar": self.calendar}


# ---- reading what Home Assistant returned -------------------------------------------------------------------------


def parse_when(value: Any, tz: ZoneInfo) -> tuple[datetime, bool]:
    """A get_events start or end: a date string is an all-day boundary, anything else an instant."""
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=tz)), False
    if isinstance(value, date):
        return datetime.combine(value, time(0), tzinfo=tz), True
    text = str(value).strip()
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), time(0), tzinfo=tz), True
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed, False


def parse_events(response: dict[str, Any] | None, tz: ZoneInfo) -> list[Occurrence]:
    """Every event of a calendar.get_events response, keyed by the calendar it came from."""
    out: list[Occurrence] = []
    for calendar, payload in (response or {}).items():
        events = payload.get("events") if isinstance(payload, dict) else None
        for raw in events or []:
            if not isinstance(raw, dict) or "start" not in raw:
                continue
            try:
                start, all_day = parse_when(raw["start"], tz)
                end, _ = parse_when(raw.get("end") or raw["start"], tz)
            except (TypeError, ValueError):
                continue
            if end < start:
                end = start
            out.append(Occurrence(summary=str(raw.get("summary") or "").strip() or "(untitled)", start=start, end=end,
                                  all_day=all_day, calendar=calendar, location=raw.get("location") or None,
                                  description=raw.get("description") or None, status=raw.get("status") or None))
    return out


def assign_people(occurrences: Iterable[Occurrence], people: Iterable[Person]) -> None:
    """An event belongs to everyone whose calendar it is on; a household calendar's event belongs to nobody."""
    owners: dict[str, list[str]] = {}
    for person in people:
        for calendar in person.calendars:
            owners.setdefault(calendar, []).append(person.id)
    for occ in occurrences:
        occ.person_ids = list(owners.get(occ.calendar, []))


def dedupe(occurrences: Iterable[Occurrence]) -> list[Occurrence]:
    """The same event on two people's calendars is one event for both of them."""
    seen: dict[tuple[str, str, str], Occurrence] = {}
    for occ in occurrences:
        key = (occ.summary.casefold(), occ.start.isoformat(), occ.end.isoformat())
        if key in seen:
            for pid in occ.person_ids:
                if pid not in seen[key].person_ids:
                    seen[key].person_ids.append(pid)
        else:
            seen[key] = occ
    return sorted(seen.values(), key=lambda o: (o.start, not o.all_day, o.summary))


# ---- today and the week -------------------------------------------------------------------------------------------


def today_board(occurrences: Iterable[Occurrence], people: list[Person], today: date, tz: ZoneInfo) -> dict[str, Any]:
    """The TV's Today: an all-day band, then a column per person, then the Household column."""
    on_day = [o for o in occurrences if today in o.days_in(tz)]
    all_day = [o for o in on_day if o.all_day]
    timed = sorted((o for o in on_day if not o.all_day), key=lambda o: o.start)
    columns = [{"person": p.id, "events": [o.present() for o in timed if p.id in o.person_ids]} for p in people]
    household = [o.present() for o in timed if not o.person_ids]
    return {"all_day": [o.present() for o in all_day], "columns": columns, "household": household,
            "count": len(on_day)}


def upcoming(occurrences: Iterable[Occurrence], today: date, days: int, tz: ZoneInfo) -> list[dict[str, Any]]:
    """The days after today that have something on, each with its events; a multi-day event appears on each day."""
    by_day: dict[date, list[Occurrence]] = {}
    for occ in occurrences:
        for day in occ.days_in(tz):
            if today < day <= today + timedelta(days=days):
                by_day.setdefault(day, []).append(occ)
    return [{"date": day.isoformat(), "events": [o.present() for o in sorted(items, key=lambda o: (not o.all_day, o.start))]}
            for day, items in sorted(by_day.items())]


# ---- birthdays ----------------------------------------------------------------------------------------------------


def next_anniversary(month: int, day: int, today: date) -> date:
    """The next time this month and day come round, today included; 29 February falls on the 28th in other years."""
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = date(year, month, 28)
        if candidate >= today:
            return candidate
    return date(today.year + 1, month, min(day, 28))


def birthday_name(summary: str) -> str:
    for pattern in BIRTHDAY_NAME:
        m = pattern.match(summary.strip())
        if m and m.group(1).strip():
            return m.group(1).strip()
    return summary.strip()


def birthdays(people: Iterable[Person], contacts: Iterable[tuple[str, date]], calendar_events: Iterable[Occurrence],
              today: date, tz: ZoneInfo, limit: int) -> dict[str, Any]:
    """Everyone's next birthday, soonest first: the household's own, the birthday-only contacts, and a birthdays
    calendar's events (Outlook's own, or a shared Family birthdays calendar). The same person twice is one entry."""
    found: dict[str, dict[str, Any]] = {}

    def add(name: str, when: date, born: int | None, source: str, person_id: str | None = None) -> None:
        key = name.casefold()
        days = (when - today).days
        entry = {"name": name, "date": when.isoformat(), "days": days, "age": (when.year - born) if born else None,
                 "person": person_id, "source": source}
        if key not in found or days < found[key]["days"]:
            found[key] = entry

    for person in people:
        if person.birthday:
            add(person.name, next_anniversary(person.birthday.month, person.birthday.day, today), person.birthday.year,
                "person", person.id)
    for name, born in contacts:
        add(name, next_anniversary(born.month, born.day, today), born.year if born.year > 1900 else None, "contact")
    for occ in calendar_events:
        when = occ.date_in(tz)
        if when < today:
            when = next_anniversary(when.month, when.day, today)
        year = YEAR.search(occ.description or "")
        add(birthday_name(occ.summary), when, int(year.group(1)) if year else None, "calendar")

    ordered = sorted(found.values(), key=lambda b: (b["days"], b["name"]))
    return {"next": ordered[0] if ordered else None, "today": [b for b in ordered if b["days"] == 0],
            "upcoming": ordered[:limit], "count": len(ordered)}


# ---- the Events board ---------------------------------------------------------------------------------------------


def events_board(occurrences: Iterable[Occurrence], today: date, days: int, tz: ZoneInfo) -> list[dict[str, Any]]:
    """What the family has tickets for, from today on, nearest first."""
    out = []
    for occ in sorted(occurrences, key=lambda o: o.start):
        when = occ.date_in(tz)
        if today <= when <= today + timedelta(days=days) or (occ.start.astimezone(tz).date() <= today <= occ.days_in(tz)[-1]):
            item = occ.present()
            item["date"] = when.isoformat()
            item["days"] = (when - today).days
            out.append(item)
    return out


def has_tag(categories: Iterable[str] | None, tags: Iterable[str]) -> bool:
    """Whether an event's Outlook categories put it on the Events board: matched trimmed and case-insensitively."""
    wanted = {str(t).strip().casefold() for t in tags if str(t).strip()}
    return any(str(c).strip().casefold() in wanted for c in categories or [])


# ---- trips --------------------------------------------------------------------------------------------------------


def dual_time(at: datetime, tz_a: ZoneInfo, tz_b: ZoneInfo) -> dict[str, Any]:
    a, b = at.astimezone(tz_a), at.astimezone(tz_b)
    return {"a": a.strftime("%H:%M"), "b": b.strftime("%H:%M"), "a_date": a.date().isoformat(), "b_date": b.date().isoformat(),
            "differs": a.strftime("%Y-%m-%d %H:%M") != b.strftime("%Y-%m-%d %H:%M")}


def flight_codes(*texts: str | None) -> list[str]:
    codes: list[str] = []
    for text in texts:
        for m in FLIGHT_CODE.finditer(text or ""):
            code = f"{m.group(1)}{m.group(2)}"
            if code not in codes and not code[:2].isdigit():
                codes.append(code)
    return codes


def route_of(summary: str, location: str | None) -> tuple[str | None, str | None]:
    """Where from and where to, out of "Edinburgh (EDI) to Oslo (OSL)", "EDI → OSL" or "Flight to Oslo"."""
    for text in (location, summary):
        if not text:
            continue
        parts = [p.strip() for p in ROUTE_SPLIT.split(text, maxsplit=1) if p.strip()]
        if len(parts) == 2 and not FLIGHT_CODE.fullmatch(parts[0].replace(" ", "")):
            frm = parts[0]
            frm = re.sub(r"^(flight|fly|ferry|ferje|train|tog)\s+(from|fra)\s+", "", frm, flags=re.I)
            if re.fullmatch(r"(flight|fly|ferry|ferje|train|tog)", frm, flags=re.I):
                return None, parts[1]
            return frm, parts[1]
    m = DESTINATION.search(summary)
    if m:
        return None, m.group(1).strip()
    return None, (location or None)


def mode_of(summary: str, location: str | None, codes: list[str]) -> str:
    text = f"{summary} {location or ''}"
    for mode, pattern in MODE_WORDS:
        if pattern.search(text):
            return mode
    return "flight" if codes else "other"


def is_trip(occ: Occurrence, trip_calendars: set[str], pattern: re.Pattern[str] | None) -> bool:
    if occ.calendar in trip_calendars:
        return True
    if pattern is None or occ.all_day:
        return False
    return bool(pattern.search(occ.summary) or pattern.search(occ.location or ""))


def trip_of(occ: Occurrence, now: datetime, tz: ZoneInfo, tz_a: ZoneInfo, tz_b: ZoneInfo) -> dict[str, Any]:
    codes = flight_codes(occ.summary, occ.location, occ.description)
    frm, to = route_of(occ.summary, occ.location)
    today = now.astimezone(tz).date()
    depart_day = occ.start.astimezone(tz).date()
    has_arrival = occ.end > occ.start and not occ.all_day
    return {
        "title": occ.summary, "mode": mode_of(occ.summary, occ.location, codes), "flights": codes,
        "from": frm, "to": to, "location": occ.location, "description": occ.description, "calendar": occ.calendar,
        "all_day": occ.all_day, "people": list(occ.person_ids),
        "depart": occ.start.isoformat(), "arrive": occ.end.isoformat() if has_arrival else None,
        "depart_clocks": dual_time(occ.start, tz_a, tz_b), "arrive_clocks": dual_time(occ.end, tz_a, tz_b) if has_arrival else None,
        "date": depart_day.isoformat(), "days": (depart_day - today).days,
        "under_way": occ.start <= now < occ.end, "past": now >= occ.end,
    }


def trips(occurrences: Iterable[Occurrence], trip_calendars: set[str], pattern: str | None, now: datetime, tz: ZoneInfo,
          tz_a: ZoneInfo, tz_b: ZoneInfo, days: int) -> dict[str, Any]:
    """Every journey ahead (and the one under way), nearest first, with the next one picked out."""
    compiled = re.compile(pattern, re.I) if pattern else None
    found = []
    today = now.astimezone(tz).date()
    for occ in sorted(occurrences, key=lambda o: o.start):
        if not is_trip(occ, trip_calendars, compiled):
            continue
        trip = trip_of(occ, now, tz, tz_a, tz_b)
        if trip["past"] or trip["days"] > days:
            continue
        found.append(trip)
    return {"next": found[0] if found else None, "trips": found, "count": len(found), "today": today.isoformat()}


# ---- chores -------------------------------------------------------------------------------------------------------


@dataclass
class Item:
    uid: str
    summary: str
    status: str
    due: date | None = None
    description: str | None = None

    @property
    def done(self) -> bool:
        return self.status == "completed"


def parse_due(value: Any, tz: ZoneInfo) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (parsed.astimezone(tz) if parsed.tzinfo else parsed).date()
    except ValueError:
        return None


def parse_items(payload: dict[str, Any] | None, tz: ZoneInfo) -> list[Item]:
    """The items of one list from a todo.get_items response (the value under the entity id)."""
    out: list[Item] = []
    for raw in (payload or {}).get("items") or []:
        if not isinstance(raw, dict):
            continue
        uid = str(raw.get("uid") or raw.get("summary") or "")
        if not uid:
            continue
        out.append(Item(uid=uid, summary=str(raw.get("summary") or "").strip(), status=str(raw.get("status") or "needs_action"),
                        due=parse_due(raw.get("due"), tz), description=raw.get("description") or None))
    return out


def points_of(summary: str, description: str | None, default: int) -> tuple[str, int]:
    """"Take the bins out (2 pts)" is two points and the title without the brackets."""
    for text in (summary, description or ""):
        for pattern in POINTS_PATTERNS:
            m = pattern.search(text)
            if m:
                title = POINTS_PATTERNS[0].sub("", summary)
                title = POINTS_PATTERNS[1].sub("", title)
                title = re.sub(r"\s{2,}", " ", title).strip(" -:")
                return title or summary, max(0, int(m.group(1)))
    return summary, default


def chore_view(item: Item, default: int) -> dict[str, Any]:
    title, points = points_of(item.summary, item.description, default)
    return {"uid": item.uid, "summary": item.summary, "title": title, "points": points,
            "due": item.due.isoformat() if item.due else None, "done": item.done}


def chores_today(items: Iterable[Item], today: date, default: int) -> dict[str, Any]:
    """What is still to do today (due today, overdue, or undated), what is for later, and what is already ticked."""
    open_now, later, done = [], [], []
    for item in items:
        view = chore_view(item, default)
        if item.done:
            done.append(view)
        elif item.due is None or item.due <= today:
            view["overdue"] = item.due is not None and item.due < today
            open_now.append(view)
        else:
            later.append(view)
    open_now.sort(key=lambda c: (c["due"] or "9999", c["title"]))
    later.sort(key=lambda c: (c["due"] or "9999", c["title"]))
    return {"open": open_now, "later": later, "done": done, "open_count": len(open_now),
            "open_points": sum(c["points"] for c in open_now)}


def list_view(entity_id: str, name: str, items: Iterable[Item]) -> dict[str, Any]:
    """One to-do list for the Lists board: its open items in the list's own order (a note under each, without any
    migration marker line), and how many are ticked."""
    open_items: list[dict[str, Any]] = []
    done = 0
    for item in items:
        if item.done:
            done += 1
            continue
        note = " ".join(line.strip() for line in (item.description or "").splitlines()
                        if line.strip() and not line.strip().startswith("[familyhub:"))
        open_items.append({"uid": item.uid, "summary": item.summary, "due": item.due.isoformat() if item.due else None,
                           "note": note or None})
    return {"entity": entity_id, "name": name, "open": open_items, "open_count": len(open_items), "done_count": done}


# ---- the completion ledger ----------------------------------------------------------------------------------------
# Home Assistant's to-do items carry no completion time, and Microsoft To Do spawns the next occurrence of a repeating
# chore the moment one is ticked, so the board keeps its own record: an item that was open at one read and completed
# (or gone) at the next was done in between, by the person whose list it is.


def ledger_update(ledger: list[dict[str, Any]], person_id: str, before: list[Item] | None, after: list[Item], now: datetime,
                  default: int, count_vanished: bool) -> list[dict[str, Any]]:
    """New ledger entries for this read. `before` is None on the first read, which records nothing."""
    if before is None:
        return []
    was_open = {i.uid: i for i in before if not i.done}
    now_by_uid = {i.uid: i for i in after}
    added = []
    recorded = {(e["person"], e["uid"]) for e in ledger}
    for uid, item in was_open.items():
        current = now_by_uid.get(uid)
        done = (current is not None and current.done) or (current is None and count_vanished)
        if not done or (person_id, uid) in recorded:
            continue
        title, points = points_of(item.summary, item.description, default)
        added.append({"person": person_id, "uid": uid, "title": title, "points": points, "at": now.isoformat(),
                      "date": now.date().isoformat()})
    return added


def prune_ledger(ledger: list[dict[str, Any]], today: date, keep_days: int) -> list[dict[str, Any]]:
    floor = (today - timedelta(days=keep_days)).isoformat()
    return [e for e in ledger if str(e.get("date", "")) >= floor]


def week_start(today: date, first_weekday: int = 0) -> date:
    return today - timedelta(days=(today.weekday() - first_weekday) % 7)


def points_summary(ledger: Iterable[dict[str, Any]], person_id: str, today: date, first_weekday: int = 0) -> dict[str, Any]:
    start = week_start(today, first_weekday)
    mine = [e for e in ledger if e.get("person") == person_id]
    week = [e for e in mine if start.isoformat() <= str(e.get("date", "")) <= today.isoformat()]
    day = [e for e in week if e.get("date") == today.isoformat()]
    return {"week_start": start.isoformat(), "points_week": sum(int(e.get("points", 0)) for e in week),
            "done_week": len(week), "points_today": sum(int(e.get("points", 0)) for e in day),
            "done_today": [{"title": e.get("title"), "points": e.get("points"), "at": e.get("at")} for e in day]}
