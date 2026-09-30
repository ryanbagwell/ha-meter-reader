"""The Utility Meter Reader integration.

Wraps rtlamr_python.start_listening() to run the SDR read/decode loop on a
background thread for the lifetime of the config entry. Each decoded reading
is:

  1. fired as a `rtlamr_reading` event on the HA event bus (for automations)
  2. dispatched to the sensor platform, which creates/updates one sensor
     entity per meter endpoint_id the first time it's seen.

Also registers a bundled Lovelace dashboard strategy (see frontend.py) so a
"Utility Meters" dashboard can group meters by commodity and stay current as
new ones are discovered, with no per-meter dashboard editing.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from rtlamr_python import ListenerHandle, start_listening

from .const import (
    CONF_CHIP_LENGTH,
    CONF_FREQ_CORRECTION,
    CONF_GAIN,
    CONF_METER_IDS,
    CONF_PROTOCOLS,
    CONF_SWITCH_TIMEOUT,
    DEFAULT_CHIP_LENGTH,
    DEFAULT_FREQ_CORRECTION,
    DEFAULT_GAIN,
    DEFAULT_SWITCH_TIMEOUT,
    DOMAIN,
    EVENT_METER_READING,
    SIGNAL_METER_UPDATE,
    SIGNAL_NEW_METER,
)
from .frontend import async_register_frontend

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

STORAGE_VERSION = 1
# Batches rapid successive readings into one write instead of hitting disk
# on every message — meters can transmit every few seconds.
SAVE_DELAY = 10.0


def _meters_from_storage(stored: dict[str, dict] | None) -> dict[int, dict]:
    """JSON object keys are always strings; restore them to int endpoint_ids."""
    return {int(endpoint_id): record for endpoint_id, record in (stored or {}).items()}


def _meters_to_storage(known_meters: dict[int, dict]) -> dict[str, dict]:
    return {str(endpoint_id): record for endpoint_id, record in known_meters.items()}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start the SDR listener thread and forward setup to the sensor platform."""
    settings: dict[str, Any] = {**entry.data, **entry.options}

    # Persists each meter's most recent reading, so its sensor entity can be
    # recreated with a real last-known value immediately on startup, instead
    # of showing "entity not found" until that meter transmits again.
    store: Store[dict[str, dict]] = Store(
        hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_meters"
    )
    known_meters: dict[int, dict] = _meters_from_storage(await store.async_load())

    @callback
    def _async_handle_reading(record: dict) -> None:
        hass.bus.async_fire(EVENT_METER_READING, record)

        endpoint_id = record.get("endpoint_id")
        if endpoint_id is None:
            return
        is_new = endpoint_id not in known_meters
        known_meters[endpoint_id] = record
        store.async_delay_save(lambda: _meters_to_storage(known_meters), SAVE_DELAY)
        if is_new:
            async_dispatcher_send(hass, SIGNAL_NEW_METER, record)
        async_dispatcher_send(hass, SIGNAL_METER_UPDATE.format(endpoint_id), record)

    def _on_message(record: dict) -> None:
        # Called from the listener's background thread — marshal onto the
        # event loop before touching hass state.
        hass.add_job(_async_handle_reading, record)

    handle: ListenerHandle = start_listening(
        _on_message,
        protocols=settings.get(CONF_PROTOCOLS) or None,
        meter_id=settings.get(CONF_METER_IDS) or None,
        chip_length=settings.get(CONF_CHIP_LENGTH, DEFAULT_CHIP_LENGTH),
        gain=settings.get(CONF_GAIN, DEFAULT_GAIN),
        freq_correction=settings.get(CONF_FREQ_CORRECTION, DEFAULT_FREQ_CORRECTION),
        switch_timeout=settings.get(CONF_SWITCH_TIMEOUT, DEFAULT_SWITCH_TIMEOUT),
        verbose=True,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "handle": handle,
        "known_meters": known_meters,
        "store": store,
    }

    await async_register_frontend(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed — reload the entry so the listener restarts with them."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop the listener thread and unload the sensor platform."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        stored = hass.data[DOMAIN].pop(entry.entry_id)
        # Force an immediate write so a still-pending SAVE_DELAY doesn't race
        # a reload/shutdown and lose the most recent readings.
        await stored["store"].async_save(_meters_to_storage(stored["known_meters"]))
        await hass.async_add_executor_job(stored["handle"].stop, 5.0)
    return unload_ok
