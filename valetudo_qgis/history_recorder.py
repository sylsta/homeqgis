"""Records the robot's outings into the project's history (see history_store.py).

Its own polling, whether the panel is shown or not: the robot's status every
15 s while it is on its dock, and every 2 s (status, position, Wi-Fi) once it
has left. Readings go through history_logic.OutingTracker; what is ready is
written every 10 s and at the end of each outing.

Nothing is written while the project has never been saved (there is no project
folder yet): the outing is kept in memory, and written as soon as it is saved.

No user-facing text here: the plugin turns the status keys into messages.
"""

import time

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.core import Qgis, QgsMessageLog

from .coords import v2q
from .history_logic import OutingTracker, active_rooms, job_type, map_fingerprint
from .history_store import HistoryStore, history_folder

IDLE_POLL_MS = 15_000
ACTIVE_POLL_MS = 2_000
WRITE_EVERY_S = 10
WIFI_EVERY = 3           # active polls: the Wi-Fi signal every 6 s
STATISTICS_EVERY = 5     # active polls: the area cleaned every 10 s
LOG_TAG = "DomotiQGIS"

# plugin command (client.commandSent key) -> activity it starts
COMMAND_ACTIVITY = {"start": "cleaning", "segments": "cleaning", "zone": "cleaning",
                    "goto": "go_to"}


class HistoryRecorder(QObject):
    # "recording" (detail: the file), "unsaved" (the project has no folder yet),
    # "written" (detail: the file), "error" (detail: the message)
    statusChanged = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = None
        self.tracker = OutingTracker()
        self.store = HistoryStore()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._ticks = 0
        self._last_write = 0.0
        self._pos = None
        self._rooms = []
        self._map_id = ""
        self._wifi = None
        self._presets = {}
        self._battery = None
        self._area_m2 = None
        self._outing_days = {}   # outing id -> start (Unix time): its file's day
        self._unsaved_told = False
        self._capabilities = set()

    # -- life cycle ----------------------------------------------------------------

    def start(self, client, capabilities=None):
        self.stop()
        self.client = client
        self._capabilities = set(capabilities or [])
        for signal, slot in self._connections():
            signal.connect(slot)
        client.fetch_timers(quiet=True)
        self._timer.start(IDLE_POLL_MS)
        self._tick()

    def stop(self):
        """Disconnect (the robot or QGIS goes away): close the outing as "stopped"."""
        self._timer.stop()
        if self.client is not None:
            for signal, slot in self._connections():
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self.client = None
        self.tracker.finish(time.time())
        self._write(force=True)

    def set_capabilities(self, capabilities):
        self._capabilities = set(capabilities or [])

    def _connections(self):
        c = self.client
        return [(c.attributesReceived, self._on_attributes), (c.mapReceived, self._on_map),
                (c.mapPeeked, self._on_map), (c.wifiReceived, self._on_wifi),
                (c.timersReceived, self._on_timers),
                (c.currentStatisticsReceived, self._on_statistics),
                (c.commandSent, self._on_command)]

    # -- polling -------------------------------------------------------------------

    def _tick(self):
        client = self.client
        if client is None:
            return
        client.fetch_attributes(quiet=True)
        if self.tracker.outing is None:
            return
        self._ticks += 1
        client.peek_map()
        if self._ticks % WIFI_EVERY == 0:
            client.fetch_wifi(quiet=True)
        if self._ticks % STATISTICS_EVERY == 0 and \
                "CurrentStatisticsCapability" in self._capabilities:
            client.fetch_current_statistics(quiet=True)
        if time.time() - self._last_write >= WRITE_EVERY_S:
            self._write()

    def _on_command(self, key):
        activity = COMMAND_ACTIVITY.get(key)
        if activity:
            self.expect(activity)

    def expect(self, activity):
        """The plugin starts something (its Go to wins over the zone cleaning that
        emulates it on robots without a native Go to)."""
        self.tracker.expect(activity, time.time())

    # -- readings ------------------------------------------------------------------

    def _on_map(self, map_json):
        for entity in (map_json or {}).get("entities", []):
            points = entity.get("points") or []
            if entity.get("type") == "robot_position" and len(points) >= 2:
                point = v2q(points[0], points[1])
                self._pos = (point.x(), point.y())
                break
        self._rooms = active_rooms(map_json)
        self._map_id = map_fingerprint(map_json) or self._map_id

    def _on_wifi(self, wifi):
        signal = ((wifi or {}).get("details") or {}).get("signal")
        self._wifi = int(signal) if signal is not None else None

    def _on_timers(self, timers):
        self.tracker.timers = list(timers or [])

    def _on_statistics(self, items):
        for item in items or []:
            if isinstance(item, dict) and item.get("type") == "area" and item.get("value") is not None:
                self._area_m2 = round(float(item["value"]) / 10000, 2)   # cm² -> m²

    def _on_attributes(self, attributes):
        state = flag = None
        for attr in attributes or []:
            cls = attr.get("__class")
            if cls == "StatusStateAttribute":
                state, flag = attr.get("value"), attr.get("flag")
            elif cls == "BatteryStateAttribute":
                self._battery = int(attr.get("level") or 0)
            elif cls == "PresetSelectionStateAttribute" and attr.get("type"):
                self._presets[attr["type"]] = attr.get("value")
        was_out = self.tracker.outing is not None
        now = time.time()
        if not was_out and state not in (None, "docked"):
            self._area_m2 = None
            if self.client is not None:
                self.client.fetch_timers(quiet=True)   # for "scheduled"
        out = self.tracker.update(now, state, flag, self._pos, self._battery, self._wifi,
                                  job_type(self._presets), self._rooms, self._map_id)
        if out and self.tracker.outing is not None:
            outing = self.tracker.outing
            self._outing_days.setdefault(outing["outing"], outing["start"])
            if self._area_m2 is not None:
                outing["area_m2"] = self._area_m2
        if out != was_out:
            self._timer.setInterval(ACTIVE_POLL_MS if out else IDLE_POLL_MS)
            self._ticks = 0
            if out:
                self._pos = None   # a fresh position for the new outing
                self.client and self.client.peek_map()
        if was_out and not out:
            self._write(force=True)   # the outing just ended

    # -- writing -------------------------------------------------------------------

    def _write(self, force=False):
        self._last_write = time.time()
        folder = history_folder()
        if folder is None:
            if self.tracker.outing is not None and not self._unsaved_told:
                self._unsaved_told = True
                self.statusChanged.emit("unsaved", "")
            return   # kept in memory: written once the project is saved
        points = self.tracker.pop_points()
        segments = self.tracker.pop_segments()
        outings = self.tracker.pop_outings()
        if not (points or segments or outings):
            return
        try:
            written = self.store.write(folder, points, segments, outings, self._outing_days)
        except OSError as exc:
            QgsMessageLog.logMessage(f"History: {exc}", LOG_TAG, Qgis.MessageLevel.Warning)
            self.statusChanged.emit("error", str(exc))
            return
        for outing in outings:
            self._outing_days.pop(outing["outing"], None)
        if written:
            self.statusChanged.emit("written" if outings else "recording", written[-1])
