"""Config flow for RTL-AMR Smart Meter."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from rtlamr_python import ALL_PROTOCOLS, DEFAULT_PROTOCOLS

from .const import (
    CONF_FREQ_CORRECTION,
    CONF_GAIN,
    CONF_METER_IDS,
    CONF_METER_SCALES,
    CONF_MULTIPLIER,
    CONF_PROTOCOLS,
    CONF_SWITCH_TIMEOUT,
    CONF_UNIT,
    DEFAULT_FREQ_CORRECTION,
    DEFAULT_GAIN,
    DEFAULT_MULTIPLIER,
    DEFAULT_SWITCH_TIMEOUT,
    DOMAIN,
    UNIT_SUGGESTIONS,
)


def _meter_ids_default(value: list[int] | None) -> str:
    return " ".join(str(meter_id) for meter_id in value) if value else ""


def _parse_meter_ids(raw: str) -> list[int] | None:
    """Turn a space/comma separated string into a list[int], or None for "all"."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    return [int(part) for part in cleaned.replace(",", " ").split()]


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_PROTOCOLS,
                default=defaults.get(CONF_PROTOCOLS, list(DEFAULT_PROTOCOLS)),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(ALL_PROTOCOLS),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_METER_IDS, default=defaults.get(CONF_METER_IDS, "")
            ): str,
            vol.Optional(
                CONF_GAIN, default=defaults.get(CONF_GAIN, DEFAULT_GAIN)
            ): str,
            vol.Optional(
                CONF_FREQ_CORRECTION,
                default=defaults.get(CONF_FREQ_CORRECTION, DEFAULT_FREQ_CORRECTION),
            ): int,
            vol.Optional(
                CONF_SWITCH_TIMEOUT,
                default=defaults.get(CONF_SWITCH_TIMEOUT, DEFAULT_SWITCH_TIMEOUT),
            ): vol.Coerce(float),
        }
    )


def _meter_field(endpoint_id: int, field: str) -> str:
    return f"meter_{endpoint_id}_{field}"


def _meters_schema(
    known_meters: set[int], current_scales: dict[str, dict[str, Any]]
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    for endpoint_id in sorted(known_meters):
        saved = current_scales.get(str(endpoint_id), {})
        fields[
            vol.Optional(
                _meter_field(endpoint_id, CONF_MULTIPLIER),
                default=saved.get(CONF_MULTIPLIER, DEFAULT_MULTIPLIER),
            )
        ] = vol.Coerce(float)
        fields[
            vol.Optional(
                _meter_field(endpoint_id, CONF_UNIT),
                default=saved.get(CONF_UNIT, ""),
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=UNIT_SUGGESTIONS,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    return vol.Schema(fields)


def _process_meters_input(
    known_meters: set[int], user_input: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    scales: dict[str, dict[str, Any]] = {}
    for endpoint_id in known_meters:
        multiplier = user_input.get(
            _meter_field(endpoint_id, CONF_MULTIPLIER), DEFAULT_MULTIPLIER
        )
        unit = user_input.get(_meter_field(endpoint_id, CONF_UNIT), "")
        scales[str(endpoint_id)] = {CONF_MULTIPLIER: multiplier, CONF_UNIT: unit}
    return scales


class _InvalidInput(Exception):
    """Raised when user-submitted config flow data fails validation."""


def _process_input(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    if not data.get(CONF_PROTOCOLS):
        raise _InvalidInput("invalid_protocols")
    try:
        data[CONF_METER_IDS] = _parse_meter_ids(user_input.get(CONF_METER_IDS, ""))
    except ValueError as err:
        raise _InvalidInput("invalid_meter_ids") from err
    return data


class RtlamrConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RTL-AMR Smart Meter.

    Only one RTL-SDR dongle/config entry is supported per HA instance.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            try:
                data = _process_input(user_input)
            except _InvalidInput as err:
                errors["base"] = str(err)
            else:
                return self.async_create_entry(title="RTL-AMR Smart Meter", data=data)

        return self.async_show_form(
            step_id="user", data_schema=_schema({}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> RtlamrOptionsFlow:
        return RtlamrOptionsFlow(config_entry)


class RtlamrOptionsFlow(OptionsFlow):
    """Handle options (protocols, meter filter, gain, per-meter scaling, etc.)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._data: dict[str, Any] = {}

    def _known_meters(self) -> set[int]:
        stored = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        return stored.get("known_meters", set())

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        current = {**self._config_entry.data, **self._config_entry.options}

        if user_input is not None:
            try:
                data = _process_input(user_input)
            except _InvalidInput as err:
                errors["base"] = str(err)
            else:
                self._data = {**current, **data}
                if self._known_meters():
                    return await self.async_step_meters()
                return self.async_create_entry(title="", data=self._data)

        defaults = {
            **current,
            CONF_METER_IDS: _meter_ids_default(current.get(CONF_METER_IDS)),
        }
        return self.async_show_form(
            step_id="init", data_schema=_schema(defaults), errors=errors
        )

    async def async_step_meters(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Per-meter display multiplier and unit, one pair of fields per known meter."""
        known_meters = self._known_meters()

        if user_input is not None:
            self._data[CONF_METER_SCALES] = _process_meters_input(
                known_meters, user_input
            )
            return self.async_create_entry(title="", data=self._data)

        current_scales = self._config_entry.options.get(CONF_METER_SCALES, {})
        return self.async_show_form(
            step_id="meters",
            data_schema=_meters_schema(known_meters, current_scales),
        )
