# Family Board

The family's calendars, birthdays, events, trips and chores on one Home Assistant dashboard, the same in every house.
Self-contained: it signs in to Microsoft itself, turns Outlook calendars and To Do lists into Home Assistant entities,
builds the board from them, and draws it with its own cards. No other integration is involved.

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
   as an Integration, download **Family Board**, restart Home Assistant.
2. Settings > Devices & services > Add integration > **Family Board** > **A Microsoft account**. Leave the application
   id and tenant as they are (the household's own app registration), press Submit, and the next screen shows a code:
   open the address on your phone, type the code, sign in as the account you want (work, school, Outlook.com or
   Hotmail) and accept the permissions. The screen moves on by itself. Then give the account a short name (it leads
   every entity id, so use the same name in every house), tick the calendars and To Do lists this house should see, and
   finish. Repeat for every account: Mark's work, Mark's personal, Malin's.
3. Add integration > **Family Board** > **The family board**: name the household and its two homes with their time
   zones, then pick the calendars that feed the board (all optional, all changeable later under Configure):
   - **Household calendars**: events for everyone (the Household column on Today).
   - **Birthday calendars**: Outlook's own Birthdays calendar, or a shared Family birthdays calendar.
   - **Events board calendars**: the gigs, matches and shows you have tickets for.
   - **Trip calendars**: every event on these is a journey. Trips are also found on everyone's calendars by their
     titles and locations (flight numbers like `DY1356`, "flight", "ferry", "train"; the pattern is an option).
4. On the board's page, **Add a person** for each member of the household: name, short name for a narrow column,
   colour, role, their calendars, their chores list and their birthday. **Add a birthday** for anybody the house keeps
   a date for and nothing else.
5. Put the cards on a dashboard. Each card finds its sensor by itself, so the whole Family view is:

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

## The Microsoft side

The sign-in is the OAuth device code flow against an app registration you own. It needs the registration to be a
public client (device code allowed) with the delegated permissions `User.Read`, `offline_access`, `Calendars.Read`
and `Tasks.ReadWrite`, and an audience that includes the accounts you will sign in (work or school in any tenant,
and personal accounts). No client secret and no redirect URI are needed for this flow. Tokens are refreshed by the
integration and kept on the config entry; when Microsoft stops refreshing them (a password change, consent withdrawn),
the entry asks to be signed in again.

What becomes an entity: a `calendar.<name>_<calendar>` per ticked Outlook calendar (read-only, with the current or
next event as its state and the full range available to the calendar panel and to `calendar.get_events`), and a
`todo.<name>_<list>` per ticked To Do list (add, rename, tick, set a due date or a description, delete; all of it
goes to Microsoft To Do). A repeating task in To Do creates its next occurrence when ticked, which is exactly what a
chores rota needs. Outlook can also add flights, hotels and trains from confirmation emails to the calendar by itself
(Settings > Calendar > Events from email), which is how a booking turns into a trip on the board without anybody
typing it.

Family Board's own board reads entities, not Microsoft, so Google Calendar, Google Tasks, CalDAV and the core Local
calendar and Local to-do feed it just as well.

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

## Options

Board (Configure): the homes, the calendars, the trip pattern, days in the week-ahead list (7), days the Events board
looks ahead (365), days trips are looked for (180), minutes between reads (10), default points (1), and whether a
chore that disappears from its list counts as done (off). Account (Configure): its name, the calendars and lists,
minutes between reads (5).

Card options: every card takes `entity` (a sensor other than the default) and `title` (`""` for none). Today:
`max_per_column` (6), `show_household`, `show_location`. Week: `max_items` (12), `show_location`. Birthdays: `limit`
(6), `show_age`. Events: `limit` (8), `show_location`. Trip: `show_countdown`, `show_all` (the trips after the next
one), `show_people`. Chores: `entities` (which people's chores sensors, default all), `show_done`, `show_points`,
`show_later`.

## Troubleshooting

- The sign-in screen says the code expired: it lasts 15 minutes; start again for a new one.
- "Needs admin approval" at sign-in: the account's tenant does not let users consent to the permissions; its admin
  grants consent once (Entra admin center > Enterprise applications > the app > Permissions), then sign in again.
- A card says there is no Family Board sensor: the board is not set up, or the card's `entity` names a sensor that
  does not exist.
- A person has no column: they have no calendars set, or the calendar entity named on them does not exist on this
  installation (entity ids differ between houses if the accounts were given different names).
- Chores never score: the item is ticked and deleted elsewhere before the board reads again; `count_vanished_as_done`
  covers that.
- Trips missing: the event is all-day (only timed events match the pattern; put all-day journeys on a trip calendar),
  or further away than the trip days option.
- The board is stale: the sensors' `stale` attribute is true and the cards print the time of the last good read; a
  calendar or list could not be read, and the log says which.

## Development

`python -m pytest tests -q` runs the model's and the Graph parsers' tests; `python tests/render_cards.py` renders all
six cards in headless Chrome from states the model builds, at phone and wall widths; `python brand/make_brand.py`
redraws the icon.

MIT licence. Copyright (c) 2026 Mark Christie.
