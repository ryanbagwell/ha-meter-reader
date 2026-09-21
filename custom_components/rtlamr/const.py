"""Constants for the RTL-AMR Smart Meter integration."""

DOMAIN = "rtlamr"

CONF_PROTOCOLS = "protocols"
CONF_METER_IDS = "meter_ids"
CONF_GAIN = "gain"
CONF_FREQ_CORRECTION = "freq_correction"
CONF_CHIP_LENGTH = "chip_length"
CONF_SWITCH_TIMEOUT = "switch_timeout"
# Per-meter display scaling: {str(endpoint_id): {"multiplier": float, "unit": str}}.
# The raw ERT consumption count has no inherent scale — it depends on the
# physical meter's dial multiplier, which isn't transmitted in the message —
# so this has to be user-supplied per meter rather than derived.
CONF_METER_SCALES = "meter_scales"
CONF_MULTIPLIER = "multiplier"
CONF_UNIT = "unit"

DEFAULT_GAIN = "auto"
DEFAULT_FREQ_CORRECTION = 0
DEFAULT_CHIP_LENGTH = 72
DEFAULT_SWITCH_TIMEOUT = 60.0
DEFAULT_MULTIPLIER = 1.0

# Suggested (not exhaustive) unit choices for the meter-scale options step.
UNIT_SUGGESTIONS = ["kWh", "CCF", "CCY", "gal", "ft³", "m³", "therm"]

# Fired on hass.bus for every decoded reading, regardless of whether a sensor
# entity exists for that meter yet.
EVENT_METER_READING = f"{DOMAIN}_reading"

# Dispatcher signals used to hand readings from the listener thread's
# callback (marshalled onto the event loop) to the sensor platform.
SIGNAL_NEW_METER = f"{DOMAIN}_new_meter"
SIGNAL_METER_UPDATE = DOMAIN + "_update_{}"
