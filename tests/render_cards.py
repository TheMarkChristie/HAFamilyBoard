"""Render all six Family Board cards in headless Chrome, at phone width and at wall width, from states the model
itself builds out of sample events, and save screenshots.

The sample states are produced the way the integration produces them (model functions in, sensor attributes out),
so what the screenshots show is what a real sensor would feed the cards. The page inlines the cards' script and the
states (file:// pages cannot fetch), fakes the bit of `hass` the cards read, and prints script errors into the page.

    python tests/render_cards.py -> tests/cards_render_phone.png and tests/cards_render_wall.png
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _load  # noqa: E402,F401
from custom_components.family_board import const, model as m  # noqa: E402

ROOT = os.path.dirname(HERE)
CARD = os.path.join(ROOT, "custom_components", "family_board", "www", "family-board-cards.js")
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]

OSLO = ZoneInfo("Europe/Oslo")
LONDON = ZoneInfo("Europe/London")


def sample_states(now: datetime) -> list[dict]:
    today = now.date()
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    t = lambda n, hh, mm=0: (datetime.combine(today + timedelta(days=n), datetime.min.time(), tzinfo=OSLO) + timedelta(hours=hh, minutes=mm)).isoformat()  # noqa: E731
    people = [
        m.Person(id="mark", name="Mark", colour="#4f8cff", calendars=["calendar.mark", "calendar.family"], chores="todo.chores_mark", birthday=date(1979, 3, 3)),
        m.Person(id="malin", name="Malin", colour="#ff6b6b", calendars=["calendar.malin", "calendar.family"], chores="todo.chores_malin", birthday=date(1982, 11, 2)),
        m.Person(id="nicolai", name="Nicolai", colour="#51cf66", role="child", calendars=["calendar.nicolai"], chores="todo.chores_nicolai", birthday=date(2016, 10, 15)),
    ]
    response = {
        "calendar.mark": {"events": [
            {"start": t(0, 9), "end": t(0, 10), "summary": "Stand-up", "location": "Teams"},
            {"start": t(0, 13), "end": t(0, 14, 30), "summary": "Dentist", "location": "Ski tannlegesenter"},
            {"start": t(1, 8), "end": t(1, 9), "summary": "Flight to Edinburgh (DY1356)", "location": "Oslo Gardermoen (OSL) to Edinburgh (EDI)"},
            {"start": t(3, 18), "end": t(3, 20), "summary": "Five-a-side"},
        ]},
        "calendar.malin": {"events": [
            {"start": t(0, 16), "end": t(0, 17), "summary": "Frisør"},
            {"start": t(2, 19), "end": t(2, 21), "summary": "Book club", "location": "Ingrid's"},
        ]},
        "calendar.nicolai": {"events": [
            {"start": t(0, 17, 30), "end": t(0, 18, 30), "summary": "Swimming", "location": "Langhushallen"},
            {"start": t(0, 8), "end": t(0, 14), "summary": "School"},
            {"start": d(1), "end": d(2), "summary": "Inset day"},
            {"start": t(4, 10), "end": t(4, 12), "summary": "Football"},
        ]},
        "calendar.family": {"events": [
            {"start": t(0, 18, 30), "end": t(0, 20), "summary": "Dinner at Granny's"},
            {"start": d(5), "end": d(8), "summary": "Weekend in Perth"},
        ]},
        "calendar.household": {"events": [
            {"start": t(0, 7), "end": t(0, 7, 15), "summary": "Bins out"},
            {"start": t(2, 9), "end": t(2, 12), "summary": "Plumber"},
        ]},
    }
    occs = m.parse_events(response, OSLO)
    m.assign_people(occs, people)
    occs = m.dedupe(occs)
    birthdays_cal = m.parse_events({"calendar.birthdays": {"events": [
        {"start": d(4), "end": d(5), "summary": "Granny Aileen's birthday"},
        {"start": d(40), "end": d(41), "summary": "Onkel Lars sin bursdag", "description": "born 1968"},
    ]}}, OSLO)
    events_cal = m.parse_events({"calendar.events": {"events": [
        {"start": t(2, 19), "end": t(2, 22), "summary": "Rosenborg v Molde", "location": "Lerkendal"},
        {"start": t(9, 18, 30), "end": t(9, 23), "summary": "Ice Nine Kills", "location": "Sentrum Scene"},
        {"start": d(23), "end": d(24), "summary": "St Johnstone v Dundee United", "location": "McDiarmid Park"},
    ]}}, OSLO)
    trips_cal = m.parse_events({"calendar.travel": {"events": [
        {"start": t(20, 6, 15), "end": t(20, 8, 45), "summary": "Ferry: Newcastle to Amsterdam", "location": "North Shields - IJmuiden"},
    ]}}, OSLO)
    meta = {"household": "The Hus", "homes": [{"name": "Scotland", "tz": "Europe/London"}, {"name": "Norway", "tz": "Europe/Oslo"}],
            "tz": "Europe/Oslo", "today": today.isoformat(), "now": now.isoformat(), "stale": False, "people": [p.summary() for p in people]}
    common = {"household": meta["household"], "homes": meta["homes"], "people": meta["people"], "date": meta["today"], "tz": meta["tz"],
              "stale": False, "updated": meta["now"]}
    board = m.today_board(occs, people, today, OSLO)
    week = m.upcoming(occs, today, 7, OSLO)
    bd = m.birthdays(people, [("Erin", date(2016, 2, 29))], birthdays_cal, today, OSLO, 10)
    ev = m.events_board(events_cal, today, 365, OSLO)
    tr = m.trips(occs + trips_cal, {"calendar.travel"}, const.TRIP_PATTERN_DEFAULT, now, OSLO, LONDON, OSLO, 180)
    chores_items = {
        "mark": [{"uid": "m1", "summary": "Empty the dishwasher", "status": "needs_action", "due": today.isoformat()},
                 {"uid": "m2", "summary": "Book the car in (3 pts)", "status": "needs_action"}],
        "malin": [{"uid": "a1", "summary": "Water the plants", "status": "needs_action", "due": d(2)}],
        "nicolai": [{"uid": "n1", "summary": "Bins out (2 pts)", "status": "needs_action", "due": today.isoformat()},
                    {"uid": "n2", "summary": "Hoover the stairs", "status": "needs_action", "due": d(-1)},
                    {"uid": "n3", "summary": "Feed the cat", "status": "completed", "due": today.isoformat()},
                    {"uid": "n4", "summary": "Tidy room", "status": "needs_action", "due": d(3)}],
    }
    ledger = [{"person": "nicolai", "uid": "n3", "title": "Feed the cat", "points": 1, "at": now.isoformat(), "date": today.isoformat()},
              {"person": "nicolai", "uid": "x", "title": "Homework", "points": 2, "at": now.isoformat(), "date": d(-1)},
              {"person": "mark", "uid": "y", "title": "Recycling", "points": 1, "at": now.isoformat(), "date": d(-2)}]

    def state(entity_id, value, attrs, name):
        return {"entity_id": entity_id, "state": "unknown" if value is None else str(value), "last_updated": now.isoformat(),
                "attributes": dict(common, friendly_name=name, **attrs)}

    states = [
        state("sensor.family_board_today", board["count"], {"family_board": "today", "all_day": board["all_day"], "columns": board["columns"],
                                                             "everyone": board["household"], "count": board["count"]}, "Family Board Today"),
        state("sensor.family_board_week", sum(len(x["events"]) for x in week), {"family_board": "week", "days": week, "days_ahead": 7}, "Family Board Week ahead"),
        state("sensor.family_board_birthdays", bd["next"]["days"] if bd["next"] else None,
              {"family_board": "birthdays", "next": bd["next"], "today_birthdays": bd["today"], "upcoming": bd["upcoming"], "count": bd["count"]}, "Family Board Birthdays"),
        state("sensor.family_board_events", len(ev), {"family_board": "events", "events": ev, "count": len(ev)}, "Family Board Events board"),
        state("sensor.family_board_trip", tr["next"]["days"] if tr["next"] else None,
              {"family_board": "trip", "trip": tr["next"], "trips": tr["trips"], "count": tr["count"]}, "Family Board Next trip"),
    ]
    for p in people:
        items = m.parse_items({"items": chores_items[p.id]}, OSLO)
        view = m.chores_today(items, today, 1)
        view.update(m.points_summary(ledger, p.id, today))
        states.append(state(f"sensor.family_board_chores_{p.id}", view["open_count"],
                            {"family_board": "chores", "person": p.summary(), "todo_entity": p.chores, "open": view["open"], "later": view["later"],
                             "done": view["done"], "done_today": view["done_today"], "open_count": view["open_count"], "open_points": view["open_points"],
                             "points_today": view["points_today"], "points_week": view["points_week"], "done_week": view["done_week"],
                             "week_start": view["week_start"]}, f"Family Board Chores {p.name}"))
    list_items = {
        "todo.new_house": ("New House", [{"uid": "l1", "summary": "Smart light switches", "status": "needs_action", "description": "[familyhub:1]\nAisle: Other"},
                                         {"uid": "l2", "summary": "Downstairs sofa", "status": "needs_action"},
                                         {"uid": "l3", "summary": "Robot lawn mower", "status": "needs_action", "description": "Husqvarna or Segway"},
                                         {"uid": "l4", "summary": "Computer desk", "status": "completed"}]),
        "todo.tesco": ("Tesco", [{"uid": "t1", "summary": "Milk 2 l", "status": "needs_action"}, {"uid": "t2", "summary": "Eggs", "status": "completed"}]),
        "todo.oslo_packing": ("Oslo packing list", []),
    }
    lists = [m.list_view(eid, name, m.parse_items({"items": raw}, OSLO)) for eid, (name, raw) in list_items.items()]
    states.append(state("sensor.family_board_lists", sum(l["open_count"] for l in lists),
                        {"family_board": "lists", "lists": lists, "count": sum(l["open_count"] for l in lists)}, "Family Board Lists"))
    return states


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>body{{margin:0;background:#111;color:#eee;font-family:Roboto,Segoe UI,sans-serif;
--primary-text-color:#e1e1e1;--secondary-text-color:#9b9b9b;--divider-color:rgba(225,225,225,0.12);--error-color:#db4437;
--primary-color:#37e0ff;--success-color:#43a047;--warning-color:#e0a800;--secondary-background-color:#2b2b2b}}
ha-card{{display:block;background:#1c1c1c;border-radius:12px;margin:8px}} ha-icon{{display:inline-block;width:22px;height:22px;vertical-align:middle;
background:currentColor;opacity:.7;border-radius:4px;transform:scale(.6)}}
#err{{color:#f66;white-space:pre-wrap;padding:8px}} .grid{{display:grid;grid-template-columns:{columns};gap:4px;width:{width}px}}</style></head><body><div id="err"></div>
<script>window.onerror=function(m,s,l){{document.getElementById('err').textContent+=m+' @'+l+'\\n'}}</script>
<script>{card}</script>
<script>
const states={states};
const hass={{states, locale:{{language:"{language}", time_format:"24", time_zone:"server"}}, config:{{time_zone:"Europe/Oslo"}},
  callService:(d,s,data)=>{{console.log('callService',d,s,JSON.stringify(data));return Promise.resolve();}}}};
const grid=document.createElement("div"); grid.className="grid"; document.body.appendChild(grid);
for (const [tag, cfg] of [["family-today-card",{{}}],["family-trip-card",{{show_all:true}}],["family-week-card",{{}}],["family-chores-card",{{}}],["family-lists-card",{{}}],
                           ["family-birthdays-card",{{}}],["family-events-card",{{}}]]) {{
  const card=document.createElement(tag); card.setConfig(cfg); grid.appendChild(card); card.hass=hass;
}}
</script></body></html>"""


def render(states, name, width, columns, language, height):
    page = PAGE.format(card=open(CARD, encoding="utf-8").read(), states=json.dumps({s['entity_id']: s for s in states}), width=width, columns=columns,
                       language=language)
    html = os.path.join(HERE, "cards_render.html")
    open(html, "w", encoding="utf-8").write(page)
    out = os.path.join(HERE, f"cards_render_{name}.png")
    url = "file:///" + html.replace("\\", "/")
    for browser in BROWSERS:
        if not os.path.exists(browser):
            continue
        profile = tempfile.mkdtemp(prefix="card-")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}",
                        f"--window-size={width + 16},{height}", f"--screenshot={out}", url], capture_output=True, timeout=120)
        shutil.rmtree(profile, ignore_errors=True)
        if os.path.exists(out):
            print("rendered", name, "with", os.path.basename(browser), "->", out)
            return
    raise SystemExit("no browser produced a screenshot")


def main():
    now = datetime.now(OSLO).replace(hour=10, minute=12, second=0, microsecond=0)
    states = sample_states(now)
    json.dump(states, open(os.path.join(HERE, "fixtures_states.json"), "w", encoding="utf-8"), indent=1)
    render(states, "phone", 400, "1fr", "en-GB", 3400)
    render(states, "wall", 1180, "1fr 1fr 1fr", "nb-NO", 1500)


if __name__ == "__main__":
    main()
