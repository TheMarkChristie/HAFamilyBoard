# Family Board

The family's calendars, birthdays, events, trips and chores on one Home Assistant dashboard, the same in every house.

Family Board reads the calendars and to-do lists you already have in Home Assistant, whoever provides them (Microsoft
365, Google, CalDAV, a local calendar), and turns them into a handful of sensors and six cards:

| Card | What it shows |
| --- | --- |
| `custom:family-today-card` | Today, one column per person and one for everyone, with an all-day band |
| `custom:family-week-card` | The days ahead, grouped by day, with who each event is for |
| `custom:family-birthdays-card` | Whose birthday is next, in how many days, and the age they turn |
| `custom:family-events-card` | The Events board: what the family has tickets for |
| `custom:family-trip-card` | The next journey counting down, departure and arrival on both homes' clocks, flight numbers |
| `custom:family-chores-card` | Everyone's chores today, ticked right there, with points this week |

Every time is shown on both homes' clocks whenever they differ: a 14:05 out of Edinburgh is 15:05 in Oslo.

## Install

1. HACS > Integrations > three dots > Custom repositories: add `https://github.com/TheMarkChristie/HAFamilyBoard`
   as an Integration, then download **Family Board** and restart Home Assistant.
2. Settings > Devices & services > Add integration > **Family Board**: name the household and its two homes (with
   their time zones), then pick the calendars that feed the board (all optional, all changeable later under Configure):
   - **Household calendars**: events for everyone (the Household column on Today).
   - **Birthday calendars**: Outlook's own Birthdays calendar, or a shared Family birthdays calendar.
   - **Events board calendars**: the gigs, matches and shows you have tickets for.
   - **Trip calendars**: every event on these is a journey. Trips are also found on everyone's calendars by their
     titles and locations (flight numbers like `DY1356`, "flight", "ferry", "train"; the pattern is an option).
3. On the integration's page, **Add a person** for each member of the household: name, short name for a narrow column,
   colour, role, their calendars, their chores list (a to-do entity) and their birthday. **Add a birthday** for anybody
   the house keeps a date for and nothing else.
4. Put the cards on a dashboard. Each card finds its sensor by itself, so the whole Family view is:

```yaml
type: sections
sections:
  - type: grid
    cards:
      - type: custom:family-today-card
      - type: custom:family-chores-card
  - type: grid
    cards:
      - type: custom:family-trip-card
        show_all: true
      - type: custom:family-week-card
      - type: custom:family-birthdays-card
      - type: custom:family-events-card
```

The cards' script is served by the integration and registered as a dashboard resource; there is nothing else to
install. They follow the dashboard's theme and speak English or Norwegian bokmål after the user's language.

## Where the data comes from

Family Board does not sign in to anything. It calls Home Assistant's own `calendar.get_events` and `todo.get_items`
actions on the entities you chose, every 10 minutes and again within seconds of any of them changing state. That is
what makes it the same in two houses: point both installations at the same shared calendars and lists and they show
the same board.

For a Microsoft family the shared store is Microsoft 365 or Outlook.com, through two HACS integrations:

- **Microsoft 365 - Calendar** (`RogerSelwyn/MS365-Calendar`): one calendar entity per Outlook calendar, including the
  Birthdays calendar and any calendar shared with the signed-in account. Outlook can also add flights, hotels and
  trains from confirmation emails to the calendar by itself (Settings > Calendar > Events from email), which is how a
  booking turns into a trip on the board without anybody typing it.
- **Microsoft 365 - To Do** (`RogerSelwyn/MS365-ToDo`): one to-do entity per Microsoft To Do list, shared lists
  included. A repeating task in To Do (daily, weekly, chosen days) creates its next occurrence when ticked, which is
  exactly what a chores rota needs. Turn on **show completed** for the lists you use as chores.

Google Calendar, Google Tasks, CalDAV and the core Local calendar and Local to-do work the same way.

## Sensors

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.family_board_today` | events today | `all_day`, `columns` (per person), `everyone`, `people`, `homes`, `date` |
| `sensor.family_board_week` | events in the days ahead | `days` (date and events), `days_ahead` |
| `sensor.family_board_birthdays` | days to the next birthday | `next`, `today_birthdays`, `upcoming` (name, date, days, age) |
| `sensor.family_board_events` | events on the board | `events` (summary, date, days, location) |
| `sensor.family_board_trip` | days to the next departure | `trip` (title, mode, flights, from, to, depart and arrive with both clocks, under_way), `trips` |
| `sensor.family_board_chores_<person>` | chores still to do today | `open`, `later`, `done_today`, `points_week`, `points_today`, `todo_entity` |
| `sensor.family_board_points_<person>` | points this week | `done_today`, `done_week`, `week_start` |

Every board sensor carries `family_board: <kind>`, which is how the cards find them, and `people` and `homes` so a
template or an automation has the names and colours too. A birthday on a person is read from the person; the age is
the year of the next birthday minus the birth year. A birthday calendar event gives its age only if its description
holds a year.

## Chores and points

A chore is worth the points in its title, written as `(2 pts)`, `[2]` or `2 poeng` anywhere in the title or the
description; a chore without any is worth the default (an option, 1). Home Assistant's to-do items carry no completion
time, so the board keeps its own ledger: an item that was open at one read and completed (or, if you turn that option
on, gone) at the next was done in between, by the person whose list it is. Points this week count from Monday. The
ledger is kept for 60 days in the integration's storage.

Ticking a chore on the card calls `todo.update_item` on that person's list, so it is ticked in Microsoft To Do (or
wherever the list lives) too.

## Options

Configure on the integration: the homes, the calendars, the trip pattern, days in the week-ahead list (7), days the
Events board looks ahead (365), days trips are looked for (180), minutes between reads (10), default points (1), and
whether a chore that disappears from its list counts as done (off).

Card options: every card takes `entity` (a sensor other than the default) and `title` (`""` for none). Today:
`max_per_column` (6), `show_household`, `show_location`. Week: `max_items` (12), `show_location`. Birthdays: `limit`
(6), `show_age`. Events: `limit` (8), `show_location`. Trip: `show_countdown`, `show_all` (the trips after the next
one), `show_people`. Chores: `entities` (which people's chores sensors, default all), `show_done`, `show_points`,
`show_later`.

## Troubleshooting

- A card says there is no Family Board sensor: the integration is not set up, or the card's `entity` names a sensor
  that does not exist.
- A person has no column: they have no calendars set, or the calendar entity named on them does not exist on this
  installation (entity ids differ between houses if the Microsoft 365 entries were given different names).
- Chores never score: the list hides completed items (turn on show completed in Microsoft 365 - To Do), or the item
  is ticked and deleted elsewhere before the board reads again; `count_vanished_as_done` covers that.
- Trips missing: the event is all-day (only timed events match the pattern; put all-day journeys on a trip calendar),
  or further away than the trip days option.
- The board is stale: the sensors' `stale` attribute is true and the cards print the time of the last good read; a
  calendar or list could not be read, and the log says which.

## Development

`python -m pytest tests -q` runs the model's tests; `python tests/render_cards.py` renders all six cards in headless
Chrome from states the model builds, at phone and wall widths; `python brand/make_brand.py` redraws the icon.

MIT licence. Copyright (c) 2026 Mark Christie.
