"""Setup: the household and its two homes, then which calendars feed the board. Options: the same plus the tuning.
People and birthday-only contacts are subentries, added one at a time from the integration's page."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import slugify

from .const import (
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
    PALETTE,
    ROLES,
    SUBENTRY_BIRTHDAY,
    SUBENTRY_PERSON,
    TRIP_PATTERN_DEFAULT,
    ZONES,
)


def _calendars() -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain="calendar", multiple=True))


def _zone() -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=ZONES, custom_value=True, mode=SelectSelectorMode.DROPDOWN))


def _number(minimum: int, maximum: int, unit: str | None = None) -> NumberSelector:
    config: dict[str, Any] = {"min": minimum, "max": maximum, "step": 1, "mode": NumberSelectorMode.BOX}
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(NumberSelectorConfig(**config))


HOMES_SCHEMA = vol.Schema({
    vol.Required(CONF_HOUSEHOLD, default="Family"): TextSelector(),
    vol.Required(CONF_HOME_A_NAME, default=DEFAULT_HOME_A[0]): TextSelector(),
    vol.Required(CONF_HOME_A_TZ, default=DEFAULT_HOME_A[1]): _zone(),
    vol.Required(CONF_HOME_B_NAME, default=DEFAULT_HOME_B[0]): TextSelector(),
    vol.Required(CONF_HOME_B_TZ, default=DEFAULT_HOME_B[1]): _zone(),
})

CALENDARS_SCHEMA = vol.Schema({
    vol.Optional(CONF_HOUSEHOLD_CALENDARS): _calendars(),
    vol.Optional(CONF_BIRTHDAY_CALENDARS): _calendars(),
    vol.Optional(CONF_EVENTS_CALENDARS): _calendars(),
    vol.Optional(CONF_TRIPS_CALENDARS): _calendars(),
})

TUNING_SCHEMA = vol.Schema({
    vol.Required(CONF_TRIP_PATTERN, default=TRIP_PATTERN_DEFAULT): TextSelector(),
    vol.Required(CONF_DAYS_AHEAD, default=DEFAULT_DAYS_AHEAD): _number(1, 31, "days"),
    vol.Required(CONF_BOARD_DAYS, default=DEFAULT_BOARD_DAYS): _number(7, 730, "days"),
    vol.Required(CONF_TRIP_DAYS, default=DEFAULT_TRIP_DAYS): _number(7, 730, "days"),
    vol.Required(CONF_SCAN_MINUTES, default=DEFAULT_SCAN_MINUTES): _number(1, 120, "min"),
    vol.Required(CONF_DEFAULT_POINTS, default=DEFAULT_POINTS): _number(0, 100, "points"),
    vol.Required(CONF_COUNT_VANISHED, default=False): BooleanSelector(),
})


def _merge(*schemas: vol.Schema) -> vol.Schema:
    merged: dict[Any, Any] = {}
    for schema in schemas:
        merged.update(schema.schema)
    return vol.Schema(merged)


def _person_schema(colour: str) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_NAME): TextSelector(),
        vol.Optional(CONF_SHORT_NAME): TextSelector(),
        vol.Required(CONF_COLOUR, default=colour): TextSelector(TextSelectorConfig(type=TextSelectorType.COLOR)),
        vol.Required(CONF_ROLE, default=ROLES[0]): SelectSelector(
            SelectSelectorConfig(options=ROLES, translation_key="role", mode=SelectSelectorMode.DROPDOWN)),
        vol.Optional(CONF_CALENDARS): _calendars(),
        vol.Optional(CONF_CHORES): EntitySelector(EntitySelectorConfig(domain="todo")),
        vol.Optional(CONF_BIRTHDAY): DateSelector(),
    })


BIRTHDAY_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): TextSelector(),
    vol.Required(CONF_BIRTHDAY): DateSelector(),
})


class FamilyBoardConfigFlow(ConfigFlow, domain=DOMAIN):
    """One board per Home Assistant."""

    VERSION = 1

    def __init__(self) -> None:
        self._homes: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._async_abort_entries_match()
        if user_input is not None:
            self._homes = {k: (v.strip() if isinstance(v, str) else v) for k, v in user_input.items()}
            return await self.async_step_calendars()
        return self.async_show_form(step_id="user", data_schema=HOMES_SCHEMA)

    async def async_step_calendars(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            options = {**self._homes, **user_input, CONF_TRIP_PATTERN: TRIP_PATTERN_DEFAULT}
            return self.async_create_entry(title=str(self._homes.get(CONF_HOUSEHOLD) or "Family"), data={}, options=options)
        return self.async_show_form(step_id="calendars", data_schema=CALENDARS_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FamilyBoardOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_PERSON: PersonSubentryFlow, SUBENTRY_BIRTHDAY: BirthdaySubentryFlow}


class FamilyBoardOptionsFlow(OptionsFlow):
    """Everything from setup, plus the tuning."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = _merge(HOMES_SCHEMA, CALENDARS_SCHEMA, TUNING_SCHEMA)
        return self.async_show_form(step_id="init",
                                    data_schema=self.add_suggested_values_to_schema(schema, dict(self.config_entry.options)))


def _taken(entry: ConfigEntry, kind: str, name: str, except_id: str | None = None) -> bool:
    slug = slugify(name)
    return any(s.subentry_type == kind and s.subentry_id != except_id and slugify(str(s.data.get(CONF_NAME) or s.title)) == slug
               for s in entry.subentries.values())


class PersonSubentryFlow(ConfigSubentryFlow):
    """A member of the household: a name, a colour, their calendars, their chores list."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        errors: dict[str, str] = {}
        count = sum(1 for s in entry.subentries.values() if s.subentry_type == SUBENTRY_PERSON)
        if user_input is not None:
            name = str(user_input.get(CONF_NAME) or "").strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            elif _taken(entry, SUBENTRY_PERSON, name):
                errors[CONF_NAME] = "already_configured"
            else:
                return self.async_create_entry(title=name, data={**user_input, CONF_NAME: name}, unique_id=slugify(name))
        return self.async_show_form(step_id="user", data_schema=_person_schema(PALETTE[count % len(PALETTE)]), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input.get(CONF_NAME) or "").strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            elif _taken(entry, SUBENTRY_PERSON, name, subentry.subentry_id):
                errors[CONF_NAME] = "already_configured"
            else:
                return self.async_update_and_abort(entry, subentry, title=name, data={**user_input, CONF_NAME: name})
        schema = _person_schema(str(subentry.data.get(CONF_COLOUR) or PALETTE[0]))
        return self.async_show_form(step_id="reconfigure", data_schema=self.add_suggested_values_to_schema(schema, dict(subentry.data)),
                                    errors=errors)


class BirthdaySubentryFlow(ConfigSubentryFlow):
    """Somebody the house keeps a date for and nothing else: a grandparent, an uncle, a school friend."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input.get(CONF_NAME) or "").strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            elif _taken(entry, SUBENTRY_BIRTHDAY, name):
                errors[CONF_NAME] = "already_configured"
            else:
                return self.async_create_entry(title=name, data={**user_input, CONF_NAME: name}, unique_id=f"birthday_{slugify(name)}")
        return self.async_show_form(step_id="user", data_schema=BIRTHDAY_SCHEMA, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input.get(CONF_NAME) or "").strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            elif _taken(entry, SUBENTRY_BIRTHDAY, name, subentry.subentry_id):
                errors[CONF_NAME] = "already_configured"
            else:
                return self.async_update_and_abort(entry, subentry, title=name, data={**user_input, CONF_NAME: name})
        return self.async_show_form(step_id="reconfigure",
                                    data_schema=self.add_suggested_values_to_schema(BIRTHDAY_SCHEMA, dict(subentry.data)), errors=errors)
