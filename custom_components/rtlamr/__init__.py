"""The Utility Meter Reader integration.

Wraps rtlamr_python.start_listening() to run the SDR read/decode loop on a
background thread for the lifetime of the config entry. Each decoded reading
is:

  1. fired as a `rtlamr_reading` event on the HA event bus (for automations)
  2. dispatched to the sensor platform, which creates/updates one sensor
     entity per meter endpoint_id the first time it's seen.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

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

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start the SDR listener thread and forward setup to the sensor platform."""
    settings: dict[str, Any] = {**entry.data, **entry.options}
    # endpoint_id -> first record seen, so the sensor platform can pick the
    # right MeterSensor subclass (by commodity) even if it comes up late.
    known_meters: dict[int, dict] = {}

    @callback
    def _async_handle_reading(record: dict) -> None:
        hass.bus.async_fire(EVENT_METER_READING, record)

        endpoint_id = record.get("endpoint_id")
        if endpoint_id is None:
            return
        if endpoint_id not in known_meters:
            known_meters[endpoint_id] = record
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
    }

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
        await hass.async_add_executor_job(stored["handle"].stop, 5.0)
    return unload_ok
