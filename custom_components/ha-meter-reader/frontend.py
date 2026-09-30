"""Serves and registers the bundled Lovelace dashboard strategy.

See www/rtlamr-strategy.js for what it renders; this module only wires it
into Home Assistant's frontend as a static file + auto-loaded JS module.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_STRATEGY_FILENAME = "rtlamr-strategy.js"
_STRATEGY_URL_PATH = f"/{DOMAIN}_static/{_STRATEGY_FILENAME}"
_WWW_DIR = Path(__file__).parent / "www"

# Separate from hass.data[DOMAIN] (keyed by config entry id) — this flags
# whether the static path/resource is registered for the whole HA run, which
# only needs to happen once even though async_setup_entry re-runs on reload.
_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"

try:
    # HA >= 2024.7 — https://developers.home-assistant.io/blog/2024/06/18/async_register_static_paths/
    from homeassistant.components.http import StaticPathConfig

    async def _async_register_static_path(hass: HomeAssistant, url_path: str, path: str) -> None:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(url_path, path, True)]
        )
except ImportError:
    # HA < 2024.7 — this repo's declared minimum (hacs.json) predates the
    # async API above, so both paths are kept, same as HACS's own shim.
    async def _async_register_static_path(hass: HomeAssistant, url_path: str, path: str) -> None:
        hass.http.register_static_path(url_path, path, True)


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the strategy module and register it as an auto-loaded resource."""
    if hass.data.get(_REGISTERED_KEY):
        return
    await _async_register_static_path(
        hass, _STRATEGY_URL_PATH, str(_WWW_DIR / _STRATEGY_FILENAME)
    )
    add_extra_js_url(hass, _STRATEGY_URL_PATH)
    hass.data[_REGISTERED_KEY] = True
