"""The board's rules, checked without Home Assistant: python -m pytest tests -q"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import _load  # noqa: F401
from custom_components.family_board import const, model as m

OSLO = ZoneInfo("Europe/Oslo")
LONDON = ZoneInfo("Europe/London")
TODAY = date(2026, 10, 15)                      # a Thursday
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=OSLO)

MARK = m.Person(id="mark", name="Mark", colour="#4f8cff", calendars=["calendar.mark", "calendar.shared"], chores="todo.chores_mark",
                birthday=date(1979, 3, 3))
MALIN = m.Person(id="malin", name="Malin", colour="#ff6b6b", calendars=["calendar.malin", "calendar.shared"])
NICOLAI = m.Person(id="nicolai", name="Nicolai", role="child", calendars=["calendar.nicolai"], chores="todo.chores_nicolai",
                   birthday=date(2016, 10, 15))
PEOPLE = [MARK, MALIN, NICOLAI]


def events(**by_calendar):
    return {cal: {"events": evs} for cal, evs in by_calendar.items()}


def board(response):
    occs = m.parse_events(response, OSLO)
    m.assign_people(occs, PEOPLE)
    return m.dedupe(occs)


def test_all_day_is_a_date_and_timed_is_an_instant():
    occs = m.parse_events(events(**{"calendar.mark": [
        {"start": "2026-10-15", "end": "2026-10-16", "summary": "Inset day"},
        {"start": "2026-10-15T17:30:00+02:00", "end": "2026-10-15T18:30:00+02:00", "summary": "Swimming"},
    ]}), OSLO)
    inset, swim = occs
    assert inset.all_day and inset.start == datetime(2026, 10, 15, tzinfo=OSLO)
    assert not swim.all_day and swim.start.astimezone(LONDON).hour == 16
    assert inset.days_in(OSLO) == [TODAY]
    assert swim.days_in(OSLO) == [TODAY]


def test_a_week_in_oslo_covers_every_day_and_a_shared_event_is_one_event_for_both():
    occs = board(events(**{
        "calendar.mark": [{"start": "2026-10-13", "end": "2026-10-20", "summary": "Week in Oslo"}],
        "calendar.shared": [{"start": "2026-10-15T18:00:00+02:00", "end": "2026-10-15T20:00:00+02:00", "summary": "Dinner out"}],
        "calendar.malin": [{"start": "2026-10-15T18:00:00+02:00", "end": "2026-10-15T20:00:00+02:00", "summary": "Dinner out"}],
        "calendar.household": [{"start": "2026-10-15T07:30:00+02:00", "end": "2026-10-15T07:45:00+02:00", "summary": "Bins"}],
    }))
    week = next(o for o in occs if o.summary == "Week in Oslo")
    assert len(week.days_in(OSLO)) == 7
    dinner = [o for o in occs if o.summary == "Dinner out"]
    assert len(dinner) == 1 and sorted(dinner[0].person_ids) == ["malin", "mark"]
    today = m.today_board(occs, PEOPLE, TODAY, OSLO)
    assert [c["summary"] for c in today["all_day"]] == ["Week in Oslo"]
    by_person = {c["person"]: [e["summary"] for e in c["events"]] for c in today["columns"]}
    assert by_person["mark"] == ["Dinner out"] and by_person["malin"] == ["Dinner out"] and by_person["nicolai"] == []
    assert [e["summary"] for e in today["household"]] == ["Bins"]


def test_upcoming_is_grouped_by_day_after_today_and_a_multi_day_event_appears_on_each():
    occs = board(events(**{
        "calendar.mark": [{"start": "2026-10-17", "end": "2026-10-19", "summary": "Camping"},
                          {"start": "2026-10-16T09:00:00+02:00", "end": "2026-10-16T10:00:00+02:00", "summary": "Dentist"},
                          {"start": "2026-10-15T09:00:00+02:00", "end": "2026-10-15T10:00:00+02:00", "summary": "Today thing"},
                          {"start": "2026-11-15T09:00:00+02:00", "end": "2026-11-15T10:00:00+02:00", "summary": "Far away"}],
    }))
    days = m.upcoming(occs, TODAY, 7, OSLO)
    assert [d["date"] for d in days] == ["2026-10-16", "2026-10-17", "2026-10-18"]
    assert [e["summary"] for e in days[1]["events"]] == ["Camping"] and [e["summary"] for e in days[2]["events"]] == ["Camping"]


def test_birthdays_come_soonest_first_with_ages_and_without_duplicates():
    cal = m.parse_events(events(**{"calendar.birthdays": [
        {"start": "2026-10-20", "end": "2026-10-21", "summary": "Granny Aileen's birthday"},
        {"start": "2026-03-03", "end": "2026-03-04", "summary": "Mark's birthday"},            # a past occurrence of a yearly event
        {"start": "2026-12-24", "end": "2026-12-25", "summary": "Onkel Lars sin bursdag", "description": "born 1968"},
    ]}), OSLO)
    result = m.birthdays(PEOPLE, [("Erin", date(2016, 2, 29))], cal, TODAY, OSLO, 10)
    names = [b["name"] for b in result["upcoming"]]
    assert names == ["Nicolai", "Granny Aileen", "Onkel Lars", "Erin", "Mark"]
    assert result["today"][0]["name"] == "Nicolai" and result["today"][0]["age"] == 10
    assert result["next"]["days"] == 0
    erin = next(b for b in result["upcoming"] if b["name"] == "Erin")
    assert erin["date"] == "2027-02-28"                                        # no 29 February in 2027
    mark = next(b for b in result["upcoming"] if b["name"] == "Mark")
    assert mark["date"] == "2027-03-03" and mark["age"] == 48 and mark["person"] == "mark"
    assert next(b for b in result["upcoming"] if b["name"] == "Onkel Lars")["age"] == 58


def test_birthday_names_are_read_out_of_outlook_and_norwegian_titles():
    assert m.birthday_name("Malin Martnes's birthday") == "Malin Martnes"
    assert m.birthday_name("Malin’s Birthday") == "Malin"
    assert m.birthday_name("Nicolais fødselsdag") == "Nicolai"
    assert m.birthday_name("Birthday: Erin") == "Erin"
    assert m.birthday_name("Granny") == "Granny"


def test_a_flight_is_a_trip_with_its_code_route_and_both_clocks():
    occs = board(events(**{"calendar.mark": [
        {"start": "2026-10-24T14:05:00+01:00", "end": "2026-10-24T17:05:00+02:00", "summary": "Flight to Oslo (DY1356)",
         "location": "Edinburgh Airport (EDI) to Oslo Gardermoen (OSL)"},
        {"start": "2026-10-16T09:00:00+02:00", "end": "2026-10-16T10:00:00+02:00", "summary": "Dentist"},
    ]}))
    result = m.trips(occs, set(), const.TRIP_PATTERN_DEFAULT, NOW, OSLO, LONDON, OSLO, 180)
    assert result["count"] == 1
    trip = result["next"]
    assert trip["flights"] == ["DY1356"] and trip["mode"] == "flight"
    assert trip["from"] == "Edinburgh Airport (EDI)" and trip["to"] == "Oslo Gardermoen (OSL)"
    assert trip["depart_clocks"]["a"] == "14:05" and trip["depart_clocks"]["b"] == "15:05" and trip["depart_clocks"]["differs"]
    assert trip["arrive_clocks"]["b"] == "17:05"
    assert trip["days"] == 9 and not trip["under_way"]


def test_a_trips_calendar_counts_whatever_it_holds_and_an_old_trip_is_dropped():
    occs = board(events(**{"calendar.travel": [
        {"start": "2026-10-15T06:00:00+02:00", "end": "2026-10-15T23:00:00+02:00", "summary": "Drive to the cabin"},
        {"start": "2026-09-01T06:00:00+02:00", "end": "2026-09-01T09:00:00+02:00", "summary": "Ferry home"},
        {"start": "2027-06-01T06:00:00+02:00", "end": "2027-06-01T09:00:00+02:00", "summary": "Summer"},
    ]}))
    result = m.trips(occs, {"calendar.travel"}, None, NOW, OSLO, LONDON, OSLO, 180)
    assert [t["title"] for t in result["trips"]] == ["Drive to the cabin"]
    assert result["next"]["under_way"] and result["next"]["mode"] == "car" and result["next"]["days"] == 0


def test_flight_codes_ignore_postcodes_and_years():
    assert m.flight_codes("Flight BA 1234 then KL1001", "EH1 2AB", "see you in 2026") == ["BA1234", "KL1001"]
    assert m.route_of("Fly til Oslo", None) == (None, "Oslo")
    assert m.route_of("Tons of Rock", "EDI → OSL") == ("EDI", "OSL")


def test_points_are_read_off_the_title_and_the_title_is_cleaned():
    assert m.points_of("Take the bins out (2 pts)", None, 1) == ("Take the bins out", 2)
    assert m.points_of("[3] Hoover the stairs", None, 1) == ("Hoover the stairs", 3)
    assert m.points_of("Feed the cat", "5 poeng", 1) == ("Feed the cat", 5)
    assert m.points_of("Empty the dishwasher", None, 1) == ("Empty the dishwasher", 1)


def test_chores_today_split_open_later_and_done():
    items = m.parse_items({"items": [
        {"uid": "a", "summary": "Bins (2 pts)", "status": "needs_action", "due": "2026-10-15"},
        {"uid": "b", "summary": "Hoover", "status": "needs_action", "due": "2026-10-14"},
        {"uid": "c", "summary": "Wash the car", "status": "needs_action", "due": "2026-10-18"},
        {"uid": "d", "summary": "Dishwasher", "status": "completed"},
        {"uid": "e", "summary": "Homework", "status": "needs_action"},
    ]}, OSLO)
    view = m.chores_today(items, TODAY, 1)
    assert [c["title"] for c in view["open"]] == ["Hoover", "Bins", "Homework"]
    assert view["open"][0]["overdue"] and not view["open"][1]["overdue"]
    assert [c["title"] for c in view["later"]] == ["Wash the car"] and [c["title"] for c in view["done"]] == ["Dishwasher"]
    assert view["open_points"] == 4


def test_the_ledger_records_a_tick_once_and_scores_the_week():
    before = m.parse_items({"items": [{"uid": "a", "summary": "Bins (2 pts)", "status": "needs_action"},
                                      {"uid": "b", "summary": "Hoover", "status": "needs_action"}]}, OSLO)
    after = m.parse_items({"items": [{"uid": "a", "summary": "Bins (2 pts)", "status": "completed"},
                                     {"uid": "b", "summary": "Hoover", "status": "needs_action"}]}, OSLO)
    assert m.ledger_update([], "nicolai", None, after, NOW, 1, False) == []           # the first read records nothing
    entries = m.ledger_update([], "nicolai", before, after, NOW, 1, False)
    assert [(e["title"], e["points"]) for e in entries] == [("Bins", 2)]
    ledger = entries + [{"person": "nicolai", "uid": "z", "title": "Old", "points": 9, "at": "2026-10-01T10:00:00+02:00", "date": "2026-10-01"},
                        {"person": "mark", "uid": "y", "title": "Mine", "points": 3, "at": NOW.isoformat(), "date": "2026-10-15"}]
    assert m.ledger_update(ledger, "nicolai", before, after, NOW + timedelta(minutes=10), 1, False) == []  # not twice
    score = m.points_summary(ledger, "nicolai", TODAY)
    assert score["week_start"] == "2026-10-12" and score["points_week"] == 2 and score["points_today"] == 2
    assert m.points_summary(ledger, "mark", TODAY)["points_week"] == 3
    gone = m.parse_items({"items": [{"uid": "b", "summary": "Hoover", "status": "needs_action"}]}, OSLO)
    assert m.ledger_update([], "nicolai", before, gone, NOW, 1, True)[0]["title"] == "Bins"   # vanished counts when asked
    assert m.ledger_update([], "nicolai", before, gone, NOW, 1, False) == []
    assert len(m.prune_ledger(ledger, TODAY, 7)) == 2


def test_events_board_lists_what_is_ahead_with_days_to_go():
    occs = m.parse_events(events(**{"calendar.events": [
        {"start": "2026-10-18T19:00:00+02:00", "end": "2026-10-18T23:00:00+02:00", "summary": "Rosenborg v Molde", "location": "Lerkendal"},
        {"start": "2026-10-01T19:00:00+02:00", "end": "2026-10-01T23:00:00+02:00", "summary": "Been"},
        {"start": "2027-03-17", "end": "2027-03-19", "summary": "Ice Nine Kills"},
    ]}), OSLO)
    out = m.events_board(occs, TODAY, 365, OSLO)
    assert [e["summary"] for e in out] == ["Rosenborg v Molde", "Ice Nine Kills"]
    assert out[0]["days"] == 3 and out[1]["all_day"]
