"""Two things can be added: the one Family Board (the household, its homes, the calendars that feed it; people and
birthday-only contacts come afterwards as subentries), and any number of Microsoft accounts, each signed in by device
code the way FamilyHub does it, and each offering its Outlook calendars and To Do lists as entities."""
from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import slugify

from .const import (
    CONF_ACCOUNT,
    CONF_ACCOUNT_NAME,
    CONF_ACCOUNT_SCAN,
    CONF_BIRTHDAY,
    CONF_BIRTHDAY_CALENDARS,
    CONF_BOARD_DAYS,
    CONF_CALENDAR_IDS,
    CONF_CALENDARS,
    CONF_CHORES,
    CONF_CLIENT_ID,
    CONF_COLOUR,
    CONF_COUNT_VANISHED,
    CONF_DAYS_AHEAD,
    CONF_DEFAULT_POINTS,
    CONF_EVENTS_CALENDARS,
    CONF_EVENTS_TAGS,
    CONF_LISTS,
    DEFAULT_EVENTS_TAGS,
    CONF_HOME_A_NAME,
    CONF_HOME_A_TZ,
    CONF_HOME_B_NAME,
    CONF_HOME_B_TZ,
    CONF_HOUSEHOLD,
    CONF_HOUSEHOLD_CALENDARS,
    CONF_KIND,
    CONF_LIST_IDS,
    CONF_NAME,
    CONF_ROLE,
    CONF_SCAN_MINUTES,
    CONF_SHORT_NAME,
    CONF_TENANT,
    CONF_TOKENS,
    CONF_TRIP_DAYS,
    CONF_TRIP_PATTERN,
    CONF_TRIPS_CALENDARS,
    DEFAULT_ACCOUNT_SCAN,
    DEFAULT_BOARD_DAYS,
    DEFAULT_CLIENT_ID,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_HOME_A,
    DEFAULT_HOME_B,
    DEFAULT_POINTS,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_TENANT,
    DEFAULT_TRIP_DAYS,
    DOMAIN,
    ENTRY_BOARD,
    ENTRY_MICROSOFT,
    PALETTE,
    ROLES,
    SUBENTRY_BIRTHDAY,
    SUBENTRY_PERSON,
    TRIP_PATTERN_DEFAULT,
    ZONES,
)
from .graph import GraphAuthError, GraphClient, GraphError, Tokens, poll_device_login, start_device_login


def _calendars() -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain="calendar", multiple=True))


def _zone() -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=ZONES, custom_value=True, mode=SelectSelectorMode.DROPDOWN))


def _number(minimum: int, maximum: int, unit: str | None = None) -> NumberSelector:
    config: dict[str, Any] = {"min": minimum, "max": maximum, "step": 1, "mode": NumberSelectorMode.BOX}
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(NumberSelectorConfig(**config))


def entry_kind(entry: ConfigEntry) -> str:
    return str(entry.data.get(CONF_KIND) or ENTRY_BOARD)


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
    vol.Optional(CONF_EVENTS_TAGS, default=DEFAULT_EVENTS_TAGS): SelectSelector(
        SelectSelectorConfig(options=DEFAULT_EVENTS_TAGS, multiple=True, custom_value=True, mode=SelectSelectorMode.LIST)),
    vol.Optional(CONF_TRIPS_CALENDARS): _calendars(),
    vol.Optional(CONF_LISTS): EntitySelector(EntitySelectorConfig(domain="todo", multiple=True)),
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

MICROSOFT_SCHEMA = vol.Schema({
    vol.Required(CONF_CLIENT_ID, default=DEFAULT_CLIENT_ID): TextSelector(),
    vol.Required(CONF_TENANT, default=DEFAULT_TENANT): TextSelector(),
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


def _pick_schema(calendars: list[dict[str, Any]], lists: list[dict[str, Any]], defaults: dict[str, Any]) -> vol.Schema:
    """Which of the account's calendars and lists become entities."""
    cal_opts = [SelectOptionDict(value=str(c["id"]), label=str(c.get("name") or c["id"])) for c in calendars if c.get("id")]
    list_opts = [SelectOptionDict(value=str(lst["id"]), label=str(lst.get("displayName") or lst["id"])) for lst in lists if lst.get("id")]
    return vol.Schema({
        vol.Required(CONF_ACCOUNT_NAME, default=defaults.get(CONF_ACCOUNT_NAME, "")): TextSelector(),
        vol.Optional(CONF_CALENDAR_IDS, default=defaults.get(CONF_CALENDAR_IDS, [])): SelectSelector(
            SelectSelectorConfig(options=cal_opts, multiple=True, mode=SelectSelectorMode.LIST)),
        vol.Optional(CONF_LIST_IDS, default=defaults.get(CONF_LIST_IDS, [])): SelectSelector(
            SelectSelectorConfig(options=list_opts, multiple=True, mode=SelectSelectorMode.LIST)),
        vol.Required(CONF_ACCOUNT_SCAN, default=defaults.get(CONF_ACCOUNT_SCAN, DEFAULT_ACCOUNT_SCAN)): _number(1, 60, "min"),
    })


class FamilyBoardConfigFlow(ConfigFlow, domain=DOMAIN):
    """The board, or a Microsoft account."""

    VERSION = 1

    def __init__(self) -> None:
        self._homes: dict[str, Any] = {}
        self._client_id = DEFAULT_CLIENT_ID
        self._tenant = DEFAULT_TENANT
        self._challenge: dict[str, Any] | None = None
        self._task: asyncio.Task[Tokens] | None = None
        self._tokens: Tokens | None = None
        self._signin_error = "signin_failed"
        self._me: dict[str, Any] | None = None
        self._choices: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None

    # ---- what to add ----

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["board", "microsoft"])

    # ---- the board ----

    async def async_step_board(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if any(entry_kind(e) == ENTRY_BOARD for e in self._async_current_entries()):
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            self._homes = {k: (v.strip() if isinstance(v, str) else v) for k, v in user_input.items()}
            return await self.async_step_calendars()
        return self.async_show_form(step_id="board", data_schema=HOMES_SCHEMA)

    async def async_step_calendars(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            options = {**self._homes, **user_input, CONF_TRIP_PATTERN: TRIP_PATTERN_DEFAULT}
            return self.async_create_entry(title=str(self._homes.get(CONF_HOUSEHOLD) or "Family"), data={CONF_KIND: ENTRY_BOARD},
                                           options=options)
        return self.async_show_form(step_id="calendars", data_schema=CALENDARS_SCHEMA)

    # ---- a Microsoft account, by device code ----

    async def async_step_microsoft(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._client_id = str(user_input.get(CONF_CLIENT_ID) or DEFAULT_CLIENT_ID).strip()
            self._tenant = str(user_input.get(CONF_TENANT) or DEFAULT_TENANT).strip() or DEFAULT_TENANT
            try:
                self._challenge = await start_device_login(async_get_clientsession(self.hass), self._client_id, self._tenant)
            except GraphError:
                errors["base"] = "cannot_connect"
            else:
                self._task = None
                return await self.async_step_signin()
        return self.async_show_form(step_id="microsoft", errors=errors,
                                    data_schema=self.add_suggested_values_to_schema(MICROSOFT_SCHEMA, {CONF_CLIENT_ID: self._client_id, CONF_TENANT: self._tenant}))

    async def async_step_signin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the code and wait, on the same screen, for the sign-in to be finished on a phone."""
        challenge = self._challenge or {}
        if self._task is None:
            # a background task: a sign-in started while Home Assistant is still finishing its start-up must not be
            # one of the tasks the start-up waits for (it did, once, for the whole fifteen minutes of a code)
            self._task = self.hass.async_create_background_task(poll_device_login(
                async_get_clientsession(self.hass), self._client_id, str(challenge.get("device_code") or ""),
                int(challenge.get("interval") or 5), int(challenge.get("expires_in") or 900), self._tenant),
                name="family_board microsoft sign-in", eager_start=True)
        if not self._task.done():
            return self.async_show_progress(step_id="signin", progress_action="signin", progress_task=self._task,
                                            description_placeholders={"url": str(challenge.get("verification_uri") or ""),
                                                                      "code": str(challenge.get("user_code") or "")})
        task, self._task = self._task, None
        try:
            self._tokens = task.result()
        except GraphAuthError as err:
            self._signin_error = "signin_expired" if "expired" in str(err) else "signin_declined"
            return self.async_show_progress_done(next_step_id="signin_failed")
        except GraphError:
            self._signin_error = "cannot_connect"
            return self.async_show_progress_done(next_step_id="signin_failed")
        return self.async_show_progress_done(next_step_id="pick")

    async def async_step_signin_failed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_abort(reason=self._signin_error)

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Who signed in, and which of their calendars and lists the house wants."""
        assert self._tokens is not None
        client = GraphClient(async_get_clientsession(self.hass), self._client_id, self._tokens, self._tenant)
        if self._me is None:
            try:
                self._me = await client.me()
                self._choices = (await client.calendars(), await client.todo_lists())
            except GraphError:
                return self.async_abort(reason="cannot_connect")
            self._tokens = client.tokens
        me = self._me
        account = {"id": str(me.get("id") or ""), "name": str(me.get("displayName") or me.get("userPrincipalName") or "Microsoft account"),
                   "upn": str(me.get("userPrincipalName") or me.get("mail") or "")}
        await self.async_set_unique_id(f"account:{account['id']}")
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(),
                                                      data_updates={CONF_TOKENS: self._tokens.to_dict(), CONF_ACCOUNT: account})
        self._abort_if_unique_id_configured()
        calendars, lists = self._choices or ([], [])
        if user_input is not None:
            name = str(user_input.get(CONF_ACCOUNT_NAME) or "").strip() or account["name"]
            return self.async_create_entry(
                title=name,
                data={CONF_KIND: ENTRY_MICROSOFT, CONF_CLIENT_ID: self._client_id, CONF_TENANT: self._tenant, CONF_ACCOUNT: account,
                      CONF_TOKENS: self._tokens.to_dict()},
                options={CONF_ACCOUNT_NAME: name, CONF_CALENDAR_IDS: list(user_input.get(CONF_CALENDAR_IDS) or []),
                         CONF_LIST_IDS: list(user_input.get(CONF_LIST_IDS) or []),
                         CONF_ACCOUNT_SCAN: int(user_input.get(CONF_ACCOUNT_SCAN) or DEFAULT_ACCOUNT_SCAN)})
        defaults = {CONF_ACCOUNT_NAME: account["name"], CONF_CALENDAR_IDS: [str(c["id"]) for c in calendars if c.get("isDefaultCalendar")],
                    CONF_LIST_IDS: [], CONF_ACCOUNT_SCAN: DEFAULT_ACCOUNT_SCAN}
        return self.async_show_form(step_id="pick", data_schema=_pick_schema(calendars, lists, defaults),
                                    description_placeholders={"account": account["upn"] or account["name"]})

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._client_id = str(entry_data.get(CONF_CLIENT_ID) or DEFAULT_CLIENT_ID)
        self._tenant = str(entry_data.get(CONF_TENANT) or DEFAULT_TENANT)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._challenge = await start_device_login(async_get_clientsession(self.hass), self._client_id, self._tenant)
            except GraphError:
                errors["base"] = "cannot_connect"
            else:
                self._task = None
                return await self.async_step_signin()
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({}), errors=errors,
                                    description_placeholders={"account": self._get_reauth_entry().title})

    # ---- options and subentries ----

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FamilyBoardOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        if entry_kind(config_entry) == ENTRY_MICROSOFT:
            return {}
        return {SUBENTRY_PERSON: PersonSubentryFlow, SUBENTRY_BIRTHDAY: BirthdaySubentryFlow}


class FamilyBoardOptionsFlow(OptionsFlow):
    """The board's homes, calendars and tuning; or an account's calendars and lists."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if entry_kind(self.config_entry) == ENTRY_MICROSOFT:
            return await self.async_step_account()
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = _merge(HOMES_SCHEMA, CALENDARS_SCHEMA, TUNING_SCHEMA)
        return self.async_show_form(step_id="init",
                                    data_schema=self.add_suggested_values_to_schema(schema, dict(self.config_entry.options)))

    async def async_step_account(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            name = str(user_input.get(CONF_ACCOUNT_NAME) or "").strip() or self.config_entry.title
            return self.async_create_entry(data={**dict(self.config_entry.options), **user_input, CONF_ACCOUNT_NAME: name})
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        try:
            calendars = await coordinator.client.calendars()
            lists = await coordinator.client.todo_lists()
        except GraphError:
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(step_id="account", data_schema=_pick_schema(calendars, lists, dict(self.config_entry.options)),
                                    description_placeholders={"account": str(coordinator.account.get("upn") or self.config_entry.title)})


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
