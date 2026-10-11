"""The Family Board cards as a dashboard resource, so nothing has to be installed for it.

The card's script is loaded as an extra frontend module too, but the Companion app can draw a dashboard before an
extra module has arrived, and the card then stays "Custom element doesn't exist" until a page reload. Lovelace waits
for its resources before it draws, so the script is kept in the resource list as well (storage mode only; YAML
resources belong to the user).
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant

from .const import CARD_FILE, URL_BASE

_LOGGER = logging.getLogger(__name__)


def _resources(hass: HomeAssistant) -> Any | None:
    """Lovelace's resource collection when it can be changed (storage mode), else None."""
    data = hass.data.get("lovelace")
    if data is None:
        return None
    resources = data.get("resources") if isinstance(data, dict) else getattr(data, "resources", None)
    if resources is None or not hasattr(resources, "async_create_item"):
        return None
    return resources


def _is_ours(url: str) -> bool:
    return url.split("?")[0].endswith(f"/{CARD_FILE}")


async def async_ensure_card_resource(hass: HomeAssistant, url: str) -> None:
    """Exactly our current script URL in the dashboard resources: added once, updated after an update."""
    resources = _resources(hass)
    if resources is None:
        return
    try:
        await resources.async_get_info()
        ours = [item for item in resources.async_items() if _is_ours(str(item.get("url", "")))]
        if not ours:
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.debug("Added the dashboard resource %s", url)
            return
        for item in ours:
            if item.get("url") != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
                _LOGGER.debug("Updated the dashboard resource %s to %s", item.get("url"), url)
    except Exception:  # noqa: BLE001  (the card still loads as an extra module; this only helps the app)
        _LOGGER.debug("Could not update the dashboard resources", exc_info=True)


def async_schedule_card_resource(hass: HomeAssistant, url: str) -> None:
    """Once Home Assistant has started (Lovelace and its resources exist by then)."""
    if hass.state is CoreState.running:
        hass.async_create_task(async_ensure_card_resource(hass, url))
        return

    async def _started(_event: Event) -> None:
        await async_ensure_card_resource(hass, url)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _started)


async def async_remove_card_resource(hass: HomeAssistant) -> None:
    """When the last team is removed: drop the resources that point at our static path."""
    resources = _resources(hass)
    if resources is None:
        return
    try:
        await resources.async_get_info()
        for item in list(resources.async_items()):
            if str(item.get("url", "")).startswith(f"{URL_BASE}/"):
                await resources.async_delete_item(item["id"])
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not remove the dashboard resource", exc_info=True)
