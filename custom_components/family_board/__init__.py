"""Family Board: the family's calendars, birthdays, events, trips and chores as sensors for the dashboards in both
houses, plus its own cards, and its own Microsoft sign-in so Outlook calendars and To Do lists become entities here
without any other integration."""
from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .account import AccountCoordinator
from .card_resource import async_remove_card_resource, async_schedule_card_resource
from .const import CARD_FILE, CONF_KIND, DOMAIN, ENTRY_BOARD, ENTRY_MICROSOFT, URL_BASE
from .coordinator import FamilyBoardCoordinator

BOARD_PLATFORMS = [Platform.SENSOR]
ACCOUNT_PLATFORMS = [Platform.CALENDAR, Platform.TODO]
_STATIC_REGISTERED = f"{DOMAIN}_static_registered"
_CARD_URL = f"{DOMAIN}_card_url"


def _kind(entry: ConfigEntry) -> str:
    return str(entry.data.get(CONF_KIND) or ENTRY_BOARD)


def _card_hash() -> str:
    try:
        return hashlib.sha256((Path(__file__).parent / "www" / CARD_FILE).read_bytes()).hexdigest()[:10]
    except OSError:
        return "0"


async def _card_url(hass: HomeAssistant) -> str:
    """The cards' URL with a version and a hash of the file, so a changed file is never served from a browser cache."""
    if url := hass.data.get(_CARD_URL):
        return url
    integration = await async_get_integration(hass, DOMAIN)
    digest = await hass.async_add_executor_job(_card_hash)
    url = f"{URL_BASE}/{CARD_FILE}?v={integration.version}-{digest}"
    hass.data[_CARD_URL] = url
    return url


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the cards and put them in front of every dashboard; once per run."""
    if not hass.data.get(_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(Path(__file__).parent / "www"), cache_headers=False)])
        hass.data[_STATIC_REGISTERED] = True
    url = await _card_url(hass)
    frontend.add_extra_js_url(hass, url)
    async_schedule_card_resource(hass, url)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if _kind(entry) == ENTRY_MICROSOFT:
        account = AccountCoordinator(hass, entry)
        await account.async_config_entry_first_refresh()
        entry.runtime_data = account
        await hass.config_entries.async_forward_entry_setups(entry, ACCOUNT_PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_account_changed))
        return True
    board = FamilyBoardCoordinator(hass, entry)
    await board.async_load()
    await board.async_config_entry_first_refresh()
    entry.runtime_data = board
    await hass.config_entries.async_forward_entry_setups(entry, BOARD_PLATFORMS)
    entry.async_on_unload(board.async_watch())
    entry.async_on_unload(entry.add_update_listener(_async_board_changed))
    return True


async def _async_board_changed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options or a person changed: reload so the sensors match."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_account_changed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when the calendars or lists chosen change; a token refresh also updates the entry and must not."""
    account: AccountCoordinator = entry.runtime_data
    if dict(entry.options) != account.options_seen:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    platforms = ACCOUNT_PLATFORMS if _kind(entry) == ENTRY_MICROSOFT else BOARD_PLATFORMS
    return await hass.config_entries.async_unload_platforms(entry, platforms)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """A board removed drops its ledger and, with it, the cards' dashboard resource; an account removed leaves nothing."""
    if _kind(entry) != ENTRY_BOARD:
        return
    await FamilyBoardCoordinator(hass, entry).async_remove_store()
    if not any(_kind(e) == ENTRY_BOARD for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id):
        frontend.remove_extra_js_url(hass, await _card_url(hass))
        await async_remove_card_resource(hass)
