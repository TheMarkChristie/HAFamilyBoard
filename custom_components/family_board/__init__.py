"""Family Board: the family's calendars, birthdays, events, trips and chores as sensors for the dashboards in both
houses, plus its own cards: today by person, the week ahead, birthdays, the Events board, the next trip and chores."""
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

from .card_resource import async_remove_card_resource, async_schedule_card_resource
from .const import CARD_FILE, DOMAIN, URL_BASE
from .coordinator import FamilyBoardCoordinator

PLATFORMS = [Platform.SENSOR]
_STATIC_REGISTERED = f"{DOMAIN}_static_registered"
_CARD_URL = f"{DOMAIN}_card_url"

type FamilyBoardConfigEntry = ConfigEntry[FamilyBoardCoordinator]


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


async def async_setup_entry(hass: HomeAssistant, entry: FamilyBoardConfigEntry) -> bool:
    coordinator = FamilyBoardCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_watch())
    entry.async_on_unload(entry.add_update_listener(_async_changed))
    return True


async def _async_changed(hass: HomeAssistant, entry: FamilyBoardConfigEntry) -> None:
    """Options or a person changed: reload so the sensors match."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FamilyBoardConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The board was removed: drop its ledger and the cards' dashboard resource."""
    await FamilyBoardCoordinator(hass, entry).async_remove_store()
    frontend.remove_extra_js_url(hass, await _card_url(hass))
    await async_remove_card_resource(hass)
