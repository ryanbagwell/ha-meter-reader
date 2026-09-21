# Home Assistant Utility Meter Reader

A drop-in Home Assistant integration that listens for utility meter
transmissions (electric, water, gas ERT meters) using an RTL-SDR dongle and
the [rtlamr-python](https://github.com/ryanbagwell/rtlamr-python) library.

It runs the SDR read/decode loop on a background thread for the life of the
config entry. Every decoded reading is:

- fired as an `rtlamr_reading` event on the Home Assistant event bus, and
- used to create/update a `sensor.<meter>_consumption` entity, one per
  meter `endpoint_id` seen (created automatically the first time that meter
  reports in).

## Requirements

- An RTL-SDR dongle attached to (or reachable by) the machine running Home
  Assistant.
- Home Assistant with USB passthrough to that dongle (a plain Docker/venv
  install needs `--device=/dev/bus/usb`; HA OS needs the dongle passed
  through if running in a VM).

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add this repo URL, category "Integration".
3. Install "Utility Meter Reader", then restart Home Assistant.

### Manual

Copy `custom_components/rtlamr` into your Home Assistant `config/custom_components/` directory, then restart Home Assistant.

## Setup

Settings → Devices & Services → Add Integration → "Utility Meter Reader".

You'll be asked for:

| Field | Description |
|---|---|
| Protocols | Which ERT protocols to decode (`scmplus`, `scm`, `idm`, `netidm`, `r900`). Defaults to all Manchester-encoded ones. |
| Meter IDs | Space/comma separated endpoint IDs to filter to. Leave blank to accept readings from every meter in range — useful for discovering IDs, but noisy in dense areas. |
| Gain | Tuner gain in dB, or `auto`. |
| Frequency correction | PPM correction for the RTL-SDR's oscillator. |
| Switch timeout | Only relevant if you select `r900` alongside a Manchester protocol — they use different center frequencies, so the SDR alternates between them after this many seconds of silence. |

All of these can be changed later from the integration's "Configure" option;
changing them restarts the listener.

Only one config entry (one RTL-SDR dongle) is supported per Home Assistant
instance.

## Using the event

Every decoded message — including from meters you haven't turned into
entities, or ones filtered out of the sensor list — fires an
`rtlamr_reading` event. Use it directly in automations, e.g. to post
readings elsewhere or react to any meter without waiting for entity
discovery:

```yaml
automation:
  - alias: "Log every meter reading"
    trigger:
      - platform: event
        event_type: rtlamr_reading
    action:
      - service: logbook.log
        data:
          name: "Meter {{ trigger.event.data.endpoint_id }}"
          message: "{{ trigger.event.data.consumption }}"
```

Event payload matches rtlamr-python's reading dict, e.g.:

```json
{"time": "2026-01-01T00:00:00Z", "type": "SCM+", "endpoint_id": 12345678,
 "endpoint_type": 4, "consumption": 112233, "tamper": "0x0000", "packet_crc": "0x972F"}
```

## Sensor entities

Each meter shows up as a device with a single sensor, both named
"`<type>` Meter (`<endpoint_id>`)" — e.g. "Water Meter (12345678)". The type
(Water, Gas, Electric, or Other when the meter type is unknown) also selects
the sensor's icon. The sensor's state is the raw ERT consumption count — the
protocol doesn't carry the meter's scale factor, so converting it to
kWh/gallons/ft³ depends on your specific meter model and needs a template
sensor on top. All other fields from the reading (`type`, `endpoint_type`,
`tamper`, etc.) are exposed as entity attributes.

The state class is `total_increasing`, so it works with the Energy dashboard
and long-term statistics once you've applied the right unit/scale via a
template sensor or utility meter helper.

## Known limitations

- Single RTL-SDR dongle per Home Assistant instance.
- `chip_length` isn't exposed in the UI — it defaults to 72 samples (~2.36
  MHz), matching the upstream `rtlamr-python` default. Open an issue if you
  need this tunable.
- Meter scale factors aren't known by the protocol, so sensor values are raw
  consumption counts, not calibrated units.

## License

MIT — see [LICENSE](LICENSE).
