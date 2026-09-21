"""Sensor platform for Utility Meter Reader.

One sensor entity is created per meter endpoint_id, the first time a reading
for it is decoded (dynamic discovery, similar to MQTT discovery — there's no
way to know which meters exist ahead of time).
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from rtlamr_python.protocols.commodity import commodity_for_endpoint_type

from .const import (
    CONF_METER_SCALES,
    CONF_MULTIPLIER,
    CONF_UNIT,
    DEFAULT_MULTIPLIER,
    DOMAIN,
    SIGNAL_METER_UPDATE,
    SIGNAL_NEW_METER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for meters already known, and listen for new ones."""
    stored = hass.data[DOMAIN][entry.entry_id]
    known_meters: dict[int, dict] = stored["known_meters"]

    @callback
    def _add_meter(record: dict) -> None:
        async_add_entities([create_meter_sensor(entry, record)])

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_NEW_METER, _add_meter))

    # Any meters that reported in between the listener starting (in
    # async_setup_entry) and this platform coming up.
    async_add_entities(
        create_meter_sensor(entry, record) for record in known_meters.values()
    )


def _endpoint_type(record: dict) -> str | None:
    """Return the meter-type code from a record.

    SCM/SCM+ key this "endpoint_type"; IDM/NetIDM key it "ert_type" — same
    4-bit meter-type code, normalized here to one accessor.
    """
    return record.get("endpoint_type", record.get("ert_type"))


def create_meter_sensor(entry: ConfigEntry, record: dict) -> MeterSensor:
    """Build the MeterSensor subclass matching the record's commodity."""
    commodity = commodity_for_endpoint_type(_endpoint_type(record))
    return METER_SENSOR_CLASSES.get(commodity, OtherMeterSensor)(entry, record)


class MeterSensor(SensorEntity):
    """The most recent consumption reading from one meter endpoint.

    Subclasses set `_attr_icon` and `_entity_type` per commodity; use
    `create_meter_sensor` to pick the right one for a record.
    """

    _entity_type: str

    _attr_has_entity_name = True
    # name=None makes this the device's primary entity, so it takes the device
    # name ("{entity_type} Meter ({endpoint_id})") as its own name and entity_id
    # instead of being suffixed onto it. Both are only defaults applied when the
    # entity/device is first registered; renames made in the UI are kept.
    _attr_name = None
    _attr_should_poll = False
    # Raw ERT consumption counts have no inherent scale — it depends on the
    # physical meter's dial multiplier, which isn't transmitted in the
    # message — so multiplier/unit come from options (see config_flow's
    # "meters" step), defaulting to a 1:1 passthrough with no unit. The
    # value is still monotonically increasing (until the meter's counter
    # rolls over), so total_increasing still enables long-term statistics
    # and the energy/utility dashboards.
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, entry: ConfigEntry, record: dict) -> None:
        endpoint_id = record["endpoint_id"]
        self._endpoint_id = endpoint_id
        self._attr_unique_id = f"{entry.entry_id}_{endpoint_id}"

        scale = entry.options.get(CONF_METER_SCALES, {}).get(str(endpoint_id), {})
        self._multiplier: float = scale.get(CONF_MULTIPLIER, DEFAULT_MULTIPLIER)
        self._attr_native_unit_of_measurement = scale.get(CONF_UNIT) or None

        self._apply(record)

    @callback
    def _apply(self, record: dict) -> None:
        raw_consumption = record.get("consumption")
        self._attr_native_value = (
            raw_consumption * self._multiplier if raw_consumption is not None else None
        )
        attrs = {
            key: value
            for key, value in record.items()
            if key not in ("consumption", "endpoint_id", "ert_type")
        }
        if raw_consumption is not None and self._multiplier != DEFAULT_MULTIPLIER:
            attrs["raw_consumption"] = raw_consumption
        endpoint_type = _endpoint_type(record)
        if endpoint_type is not None:
            attrs["endpoint_type"] = endpoint_type
            commodity = commodity_for_endpoint_type(endpoint_type)
            if commodity is not None:
                attrs["commodity"] = commodity
        self._attr_extra_state_attributes = attrs
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._endpoint_id))},
            name=f"{self._entity_type} Meter ({self._endpoint_id})",
            model=record.get("type") or "Unknown",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates for this meter once added to hass."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_METER_UPDATE.format(self._endpoint_id),
                self._async_update_from_signal,
            )
        )

    @callback
    def _async_update_from_signal(self, record: dict) -> None:
        self._apply(record)
        self.async_write_ha_state()


class WaterMeterSensor(MeterSensor):
    """A water meter."""

    _entity_type = "Water"
    _attr_icon = "mdi:water"


class GasMeterSensor(MeterSensor):
    """A gas meter."""

    _entity_type = "Gas"
    _attr_icon = "mdi:meter-gas"


class ElectricMeterSensor(MeterSensor):
    """An electric meter."""

    _entity_type = "Electric"
    _attr_icon = "mdi:lightning-bolt"


class OtherMeterSensor(MeterSensor):
    """A meter whose commodity is unknown or unclassified."""

    _entity_type = "Other"
    _attr_icon = "mdi:gauge"


# Keyed by the names commodity_for_endpoint_type() returns.
METER_SENSOR_CLASSES: dict[str | None, type[MeterSensor]] = {
    "water": WaterMeterSensor,
    "gas": GasMeterSensor,
    "electric": ElectricMeterSensor,
}
