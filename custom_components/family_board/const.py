"""Constants for Family Board. Nothing here imports Home Assistant, so the model and its tests stay pure."""

DOMAIN = "family_board"
NAME = "Family Board"

STORAGE_VERSION = 1

# the cards, served by the integration from its www folder and registered as a dashboard resource
URL_BASE = "/family_board"
CARD_FILE = "family-board-cards.js"

# the one entry's data and options
CONF_HOUSEHOLD = "household"
CONF_HOME_A_NAME = "home_a_name"
CONF_HOME_A_TZ = "home_a_tz"
CONF_HOME_B_NAME = "home_b_name"
CONF_HOME_B_TZ = "home_b_tz"
CONF_HOUSEHOLD_CALENDARS = "household_calendars"   # events for everyone: the Household column
CONF_BIRTHDAY_CALENDARS = "birthday_calendars"     # Outlook's Birthdays calendar, or a Family birthdays calendar
CONF_EVENTS_CALENDARS = "events_calendars"         # the Events board: what the family has tickets for
CONF_TRIPS_CALENDARS = "trips_calendars"           # every event on these is a trip
CONF_TRIP_PATTERN = "trip_pattern"                 # and any event matching this, on any calendar, is one too
CONF_DAYS_AHEAD = "days_ahead"                     # the week-ahead list
CONF_BOARD_DAYS = "board_days"                     # how far the Events board looks
CONF_TRIP_DAYS = "trip_days"                       # how far ahead trips are looked for
CONF_SCAN_MINUTES = "scan_minutes"
CONF_DEFAULT_POINTS = "default_points"
CONF_COUNT_VANISHED = "count_vanished_as_done"     # a chore that disappears from its list counts as done

DEFAULT_HOME_A = ("Scotland", "Europe/London")
DEFAULT_HOME_B = ("Norway", "Europe/Oslo")
DEFAULT_DAYS_AHEAD = 7
DEFAULT_BOARD_DAYS = 365
DEFAULT_TRIP_DAYS = 180
DEFAULT_SCAN_MINUTES = 10
DEFAULT_POINTS = 1
BIRTHDAY_DAYS = 366                                # birthdays are read a year ahead so every one has a next date
UPCOMING_BIRTHDAYS = 10                            # how many the birthdays sensor lists

# an event is a trip when its title or location names a journey or carries a flight number
TRIP_PATTERN_DEFAULT = r"\b(flight|fly|flyr|ferry|ferje|ferge|train|tog|eurostar|sail(?:ing)?|cross(?:ing)?)\b|\b[A-Z]{2}\s?\d{3,4}\b"

ZONES = ["Europe/London", "Europe/Oslo", "Europe/Stockholm", "Europe/Copenhagen", "Europe/Berlin", "Europe/Paris",
         "Europe/Amsterdam", "Europe/Madrid", "Europe/Dublin", "Europe/Lisbon", "Europe/Helsinki", "America/New_York",
         "America/Los_Angeles", "UTC"]

# people and birthday-only contacts are subentries of the one Family Board entry
SUBENTRY_PERSON = "person"
SUBENTRY_BIRTHDAY = "birthday"
CONF_NAME = "name"
CONF_SHORT_NAME = "short_name"
CONF_COLOUR = "colour"
CONF_ROLE = "role"
CONF_CALENDARS = "calendars"
CONF_CHORES = "chores"                             # the person's to-do list of chores
CONF_BIRTHDAY = "birthday"
ROLES = ["adult", "child", "guest"]

# FamilyHub's person colours, handed out in turn so two children never share a hue
PALETTE = ["#4f8cff", "#ff6b6b", "#51cf66", "#fcc419", "#cc5de8", "#22b8cf", "#ff922b", "#f06595", "#94d82d", "#845ef7"]

KIND_TODAY = "today"
KIND_WEEK = "week"
KIND_BIRTHDAYS = "birthdays"
KIND_EVENTS = "events"
KIND_TRIP = "trip"
KIND_CHORES = "chores"
KIND_POINTS = "points"

LEDGER_KEEP_DAYS = 60                              # completed chores are remembered this long for the scoreboards

# two kinds of config entry: the one board, and any number of Microsoft accounts (calendars and To Do lists)
CONF_KIND = "kind"
ENTRY_BOARD = "board"
ENTRY_MICROSOFT = "microsoft"
CONF_CLIENT_ID = "client_id"
CONF_TENANT = "tenant"
CONF_ACCOUNT = "account"                           # {id, name, upn}
CONF_TOKENS = "tokens"
CONF_ACCOUNT_NAME = "account_name"                 # the prefix of this account's entity ids
CONF_CALENDAR_IDS = "calendar_ids"
CONF_LIST_IDS = "list_ids"
CONF_ACCOUNT_SCAN = "account_scan_minutes"
DEFAULT_CLIENT_ID = "6ba638f9-389d-4d0a-b862-0350e84e23bf"   # the Family Hub app registration: public client, device code sign-in
DEFAULT_TENANT = "common"
DEFAULT_ACCOUNT_SCAN = 5
ACCOUNT_DAYS_AHEAD = 14                            # how far an account's calendar entities look for their current/next event
