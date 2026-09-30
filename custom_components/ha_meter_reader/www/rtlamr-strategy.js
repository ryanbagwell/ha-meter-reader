/**
 * Lovelace dashboard strategy for the Utility Meter Reader (rtlamr) integration.
 *
 * Generates one view grouping every "rtlamr" device by commodity (water, gas,
 * electric, other). It's rebuilt from the live device/entity/state registries
 * on every render, so newly discovered meters appear automatically — no
 * dashboard editing needed as new meters report in.
 *
 * Registered as a frontend resource automatically by the integration
 * (see frontend.py); nothing to install by hand.
 *
 * To use it, add a new dashboard (Settings -> Dashboards -> Add Dashboard),
 * then switch it to this strategy via its three-dot menu -> Edit Dashboard
 * -> three-dot menu -> "Edit in YAML", replacing the content with:
 *
 *   strategy:
 *     type: custom:rtlamr-meters
 */

const DOMAIN = "rtlamr";

function memoize(fn) {
  const cache = new Map();
  return function (...args) {
    const key = JSON.stringify(args);
    if (cache.has(key)) {
      return cache.get(key);
    }
    const result = fn.apply(this, args);
    cache.set(key, result);
    return result;
  };
}

function rtlamrDevices(hass) {
  return Object.values(hass.devices).filter((device) =>
    device.identifiers.some(([domain]) => domain === DOMAIN)
  );
}

const getPrimaryEntity = memoize((hass, device) => {
  // Each meter device has exactly one entity, registered as the device's
  // primary entity (has_entity_name + name=None — see sensor.py MeterSensor).
  return Object.values(hass.entities).find(
    (candidate) => candidate.device_id === device.id
  );
})



class RtlamrMetersStrategy extends HTMLElement {
  static async generate(config, hass) {

    const devices = rtlamrDevices(hass);

    const sections = devices.map((device) => {

      const primaryEntity = getPrimaryEntity(hass, device);

      const entities = [primaryEntity?.entity_id]

      return {
        title: device.name_by_user || device.name,
        type: "grid",
        column_span: 3,
        cards: [
          {
            type: "statistics-graph",
            title: "Past 24 hours",
            entities,
            days_to_show: 1,
            chart_type: "line",
            stat_types: "state",
            period: "5minute",
          },
          {
            type: "statistics-graph",
            title: "Past 7 days",
            entities,
            days_to_show: 7,
            chart_type: "line",
            stat_types: "state",
            period: "hour",
          },
          {
            type: "statistics-graph",
            title: "Past 30 days",
            entities,
            days_to_show: 30,
            chart_type: "line",
            stat_types: "state",
            period: "day",
          }
        ]
      }
    })

    return {
      title: config.title ?? "Utility Meters",
      views: [{
        title: "Utility Meters",
        type: "sections",
        sections,
      }]
    };
  }
}

customElements.define("ll-strategy-dashboard-rtlamr-meters", RtlamrMetersStrategy);

// Lets this strategy show up in the "new dashboard" strategy picker; purely
// cosmetic — the strategy: {type: custom:rtlamr-meters} config works without it.
window.customStrategies = window.customStrategies || [];
window.customStrategies.push({
  type: "rtlamr-meters",
  strategyType: "dashboard",
  name: "Utility Meters (rtlamr)",
});
