"""What the board makes of Microsoft Graph's answers, checked without a network or Home Assistant."""
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import _load  # noqa: F401
from custom_components.family_board import graph as g

OSLO = ZoneInfo("Europe/Oslo")


def test_a_timed_event_in_the_preferred_zone_is_an_instant():
    raw = {"id": "AAMk", "iCalUId": "040000008200E", "subject": "Dentist", "isAllDay": False,
           "start": {"dateTime": "2026-10-15T13:00:00.0000000", "timeZone": "Europe/Oslo"},
           "end": {"dateTime": "2026-10-15T14:30:00.0000000", "timeZone": "Europe/Oslo"},
           "location": {"displayName": "Ski tannlegesenter"}, "bodyPreview": "Bring the card", "showAs": "busy", "categories": ["Health"]}
    ev = g.parse_event(raw, OSLO)
    assert ev["uid"] == "040000008200E" and ev["summary"] == "Dentist" and not ev["all_day"]
    assert ev["start"] == datetime(2026, 10, 15, 13, 0, tzinfo=OSLO) and ev["start"].astimezone(ZoneInfo("Europe/London")).hour == 12
    assert ev["location"] == "Ski tannlegesenter" and ev["description"] == "Bring the card" and ev["categories"] == ["Health"]


def test_an_all_day_event_is_a_date_whatever_zone_graph_answered_in():
    raw = {"id": "x", "subject": "Inset day", "isAllDay": True,
           "start": {"dateTime": "2026-10-16T00:00:00.0000000", "timeZone": "UTC"},
           "end": {"dateTime": "2026-10-17T00:00:00.0000000", "timeZone": "UTC"}}
    ev = g.parse_event(raw, OSLO)
    assert ev["all_day"] and ev["start"] == date(2026, 10, 16) and ev["end"] == date(2026, 10, 17)


def test_windows_zone_names_and_cancellations_are_handled():
    raw = {"id": "y", "subject": "Call", "isAllDay": False, "isCancelled": False,
           "start": {"dateTime": "2026-10-15T09:00:00", "timeZone": "GMT Standard Time"},
           "end": {"dateTime": "2026-10-15T09:30:00", "timeZone": "GMT Standard Time"}}
    ev = g.parse_event(raw, OSLO)
    assert ev["start"].utcoffset().total_seconds() == 3600            # BST on 15 October
    assert g.parse_event(dict(raw, isCancelled=True), OSLO) is None
    assert g.zone_of("Nonsense/Zone", OSLO) is OSLO


def test_tasks_become_to_do_items_and_old_completed_ones_drop_off():
    now = datetime(2026, 10, 15, 10, 0, tzinfo=OSLO)
    open_task = {"id": "t1", "title": "Bins out (2 pts)", "status": "notStarted", "dueDateTime": {"dateTime": "2026-10-15T00:00:00.0000000", "timeZone": "UTC"},
                 "body": {"content": "Blue bin this week", "contentType": "text"}, "recurrence": {"pattern": {"type": "weekly"}}}
    done_today = {"id": "t2", "title": "Feed the cat", "status": "completed", "completedDateTime": {"dateTime": "2026-10-15T07:05:00.0000000", "timeZone": "UTC"}}
    done_long_ago = {"id": "t3", "title": "Old", "status": "completed", "completedDateTime": {"dateTime": "2026-08-01T07:05:00.0000000", "timeZone": "UTC"}}
    a, b, c = (g.parse_task(t, OSLO, now) for t in (open_task, done_today, done_long_ago))
    assert a["status"] == "needs_action" and a["due"] == date(2026, 10, 15) and a["description"] == "Blue bin this week" and a["recurring"]
    assert b["status"] == "completed" and b["completed"].startswith("2026-10-15T07:05")
    assert c is None


def test_task_body_for_a_tick_a_rename_and_a_due_date():
    assert g.task_body(status="completed") == {"status": "completed"}
    assert g.task_body(summary="Hoover", status="needs_action")["title"] == "Hoover"
    body = g.task_body(due=date(2026, 10, 18), description="Upstairs too")
    assert body["dueDateTime"] == {"dateTime": "2026-10-18T00:00:00", "timeZone": "UTC"} and body["body"]["content"] == "Upstairs too"
    assert g.task_body(clear_due=True) == {"dueDateTime": None}


def test_tokens_round_trip_and_expiry():
    t = g.Tokens.from_response({"access_token": "a", "refresh_token": "r", "expires_in": 3600, "scope": "User.Read"})
    assert not t.expired()
    again = g.Tokens.from_dict(t.to_dict())
    assert again.refresh_token == "r" and again.access_token == "a"
    assert g.Tokens(access_token="a", refresh_token="r", expires_at=time.time() + 30).expired()
    kept = g.Tokens.from_response({"access_token": "b", "expires_in": 3600}, t)
    assert kept.refresh_token == "r"                                       # a refresh without a new refresh token keeps the old one
