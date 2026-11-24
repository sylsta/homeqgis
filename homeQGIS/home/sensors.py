"""Home Assistant sensors shown on the robot's map.

Each sensor is a Home Assistant entity (e.g. a Zigbee temperature or door
contact) pinned to a point of the map. Positions are stored locally (the robot
and Home Assistant do not know them); the live value comes from Home Assistant's
REST API, one ``GET /api/states`` call for all of them at once.

The manager owns a HomeAssistantClient, polls on a timer while active, and emits
``sensorsUpdated`` with the items to draw (see map_layers.update_sensors).
"""

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

from .ha_client import HomeAssistantClient
from ..core.i18n import tr
from ..core.settings import ha_sensors, ha_token, load_settings, set_ha_sensors

# States that mean "no reading right now" rather than a real value.
UNAVAILABLE_STATES = {"unavailable", "unknown", "none", ""}

# Entity domains worth placing on a map (a vacuum is the robot itself, etc.).
SENSOR_DOMAINS = ("sensor", "binary_sensor")


class SensorManager(QObject):
    """Polls Home Assistant for the placed sensors and emits what to draw."""

    sensorsUpdated = pyqtSignal(list)   # list of item dicts (see _build_items)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = ha_sensors()     # [{entity_id, x, y}]
        self._states = {}               # entity_id -> state object, from the last poll
        self._items = []                # last items emitted (cached, no network)
        self._client = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    # -- configuration ----------------------------------------------------------

    def _ha(self):
        """The Home Assistant client for the current settings (rebuilt on demand)."""
        cfg = load_settings()
        url, token = cfg["ha_url"], ha_token()
        if self._client is None or self._client.base_url != url or self._client.token != token:
            if self._client is not None:
                self._client.close()
            self._client = HomeAssistantClient(url, token, self)
        return self._client

    def config(self):
        return list(self._config)

    def set_config(self, sensors):
        """Replace the stored sensors, then refresh the map at once."""
        set_ha_sensors(sensors)
        self._config = ha_sensors()
        self._emit_items()        # reposition immediately with the values we already have
        self.refresh()            # and fetch fresh values

    def add_sensor(self, entity_id, x, y):
        sensors = [s for s in self._config if s["entity_id"] != entity_id]
        sensors.append({"entity_id": entity_id, "x": int(round(x)), "y": int(round(y))})
        self.set_config(sensors)

    def remove_sensor(self, entity_id):
        self.set_config([s for s in self._config if s["entity_id"] != entity_id])

    def nearest(self, x, y, max_dist_cm):
        """entity_id of the placed sensor closest to (x, y), within max_dist_cm, or None."""
        best, best_d2 = None, max_dist_cm * max_dist_cm
        for s in self._config:
            d2 = (s["x"] - x) ** 2 + (s["y"] - y) ** 2
            if d2 <= best_d2:
                best, best_d2 = s["entity_id"], d2
        return best

    def items(self):
        return list(self._items)

    # -- polling ----------------------------------------------------------------

    def start(self, interval_ms):
        if interval_ms > 0:
            self._timer.start(interval_ms)
        self.refresh()

    def stop(self):
        self._timer.stop()

    def close(self):
        self._timer.stop()
        if self._client is not None:
            self._client.close()

    def refresh(self):
        """Fetch every state once; the placed sensors are picked out of the answer."""
        if not self._config:
            self._states = {}
            self._emit_items()
            return
        self._ha().get("/states", self._on_states, self._on_error, timeout_ms=8000)

    def _on_states(self, data):
        self._states = {s["entity_id"]: s for s in data
                        if isinstance(s, dict) and s.get("entity_id")} if isinstance(data, list) \
            else {}
        self._emit_items()

    def _on_error(self, _message):
        # Keep the last known values on a transient error; mark nothing as fresh.
        self._emit_items()

    # -- entity list (for the placement picker) ---------------------------------

    def fetch_entities(self, on_ready, on_error=None):
        """Call on_ready([(entity_id, friendly_name)]) with the placeable entities."""
        def ok(data):
            entities = []
            for s in data if isinstance(data, list) else []:
                eid = s.get("entity_id", "")
                if eid.split(".", 1)[0] in SENSOR_DOMAINS:
                    name = (s.get("attributes") or {}).get("friendly_name") or eid
                    entities.append((eid, str(name)))
            entities.sort(key=lambda e: e[1].lower())
            on_ready(entities)

        def failed(message):
            if on_error:
                on_error(message if message != "401" else tr("the access token was refused"))

        self._ha().get("/states", ok, failed, timeout_ms=8000)

    # -- building the items -----------------------------------------------------

    def _build_items(self):
        items = []
        for s in self._config:
            eid = s["entity_id"]
            state = self._states.get(eid)
            attrs = (state.get("attributes") if state else None) or {}
            raw = state.get("state") if state else None
            available = raw is not None and str(raw).lower() not in UNAVAILABLE_STATES
            items.append({
                "entity_id": eid,
                "x": s["x"], "y": s["y"],
                "label": str(attrs.get("friendly_name") or eid),
                "value": raw if available else tr("—"),
                "unit": str(attrs.get("unit_of_measurement") or ""),
                "available": available,
            })
        return items

    def _emit_items(self):
        self._items = self._build_items()
        self.sensorsUpdated.emit(self._items)
