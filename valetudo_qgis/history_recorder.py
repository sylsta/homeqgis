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
from .history_logic import (PATH_LONGER, OutingTracker, active_rooms, clock_offset, job_type,
                            refine_segments, rooms_on_path,
                            map_fingerprint, map_path, path_length_m, robot_runs)
from .history_store import HistoryStore, history_folder, recorded_intervals

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
        self._map = None
        self._map_id = ""
        self._wifi = None
        self._presets = {}
        self._battery = None
        self._area_m2 = None
        self._outing_days = {}   # outing id -> start (Unix time): its file's day
        self._unsaved_told = False
        self._capabilities = set()
        self._path = []          # Valetudo's path of the current job (Valetudo frame)
        self._first_reading = True   # the next reading is the first since start()
        self._partial = False    # the outing under way began before we were watching

    # -- life cycle ----------------------------------------------------------------

    def start(self, client, capabilities=None):
        self.stop()
        self.client = client
        self._capabilities = set(capabilities or [])
        self._first_reading = True
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
        self._map = map_json   # its rooms, for the rooms of an outing
        self._path = map_path(map_json)
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
        first, self._first_reading = self._first_reading, state is None and self._first_reading
        if not was_out and state not in (None, "docked"):
            self._partial = first   # out already when we started watching
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
            self._complete_from_path()
            self._write(force=True)   # the outing just ended

    def _complete_from_path(self):
        """The outing that just ended, with Valetudo's own path of the job (all the
        way, but no times):
        - its line, when we saw only part of it (QGIS started while the robot was
          out, readings missed);
        - its segments, which join readings a few seconds apart, follow the path;
        - its rooms, when Valetudo marked none (whole-home cleaning): those the
          line went through."""
        path = [(p.x(), p.y()) for p in (v2q(x, y) for x, y in self._path)]
        folder = history_folder()
        for outing in self.tracker._outings:
            if len(path) >= 2:
                length = round(path_length_m(path), 2)
                live = outing.get("distance_m") or 0
                refined = refine_segments(outing, path)   # the path is this outing's
                if self._partial or length > live * PATH_LONGER or (refined and length >= live):
                    outing.update(geometry=path, distance_m=length, source="live+path")
                if refined:
                    self._replace_segments(folder, outing)
            if not outing.get("rooms") and outing.get("geometry"):
                outing["rooms"] = rooms_on_path(self._map,
                                                [(x, -y) for x, y in outing["geometry"]])
        self._partial = False

    def _replace_segments(self, folder, outing):
        """The outing's segments, refined: those still waiting are written as they are
        now; those already in the file are replaced."""
        spans = outing.get("spans") or []
        self.tracker._segments = [s for s in self.tracker._segments
                                  if s.get("outing") != outing["outing"]]
        if folder is None:   # nothing written yet: written once the project is saved
            self.tracker._segments += spans
            return
        try:
            self.store.replace_segments(folder, outing["outing"], spans, self._outing_days)
        except OSError as exc:
            QgsMessageLog.logMessage(f"History: {exc}", LOG_TAG, Qgis.MessageLevel.Warning)

    # -- the recorder on the robot ---------------------------------------------------

    def import_robot(self, rows, robot_now):
        """Readings of the recorder on the robot (robot_survey.parse_rows): add the
        outings QGIS did not record. Returns {"outings", "skipped", "offset_s"}, or
        None while the project has never been saved."""
        folder = history_folder()
        if folder is None or not rows:
            return None if folder is None else {"outings": 0, "skipped": 0, "offset_s": 0}
        now = time.time()
        offset = clock_offset(now, robot_now)
        times = [r["time"] + offset for r in rows]
        recorded = recorded_intervals(folder, min(times), max(times))
        if self.tracker.outing is not None:
            recorded.append((self.tracker.outing["start"], now))

        def convert(x, y):
            point = v2q(x, y)
            return point.x(), point.y()

        points, segments, outings, skipped = robot_runs(rows, offset, recorded, now,
                                                        self.tracker.timers, convert)
        days = {o["outing"]: o["start"] for o in outings}
        if outings:
            try:
                written = self.store.write(folder, points, segments, outings, days)
            except OSError as exc:
                return {"error": str(exc)}
            for path in written:
                self.statusChanged.emit("written", path)
        return {"outings": len(outings), "skipped": skipped, "offset_s": offset}

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
