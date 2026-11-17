"""Asynchronous HTTP client for the Valetudo REST API (/api/v2).

All requests go through QgsNetworkAccessManager: they never block the UI and
they honour the QGIS proxy settings. Results are broadcast with Qt signals.

This module contains no user-facing text: commandDone emits a command key
(see COMMAND_KEYS) that the UI layer turns into a translated label.
"""

import email.utils
import json
import time

from qgis.PyQt.QtCore import QObject, QUrl, QTimer, QByteArray, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest, QNetworkReply
from qgis.core import QgsApplication, QgsNetworkAccessManager, QgsPointXY

from .coords import q2v

COMMAND_KEYS = ("start", "pause", "stop", "home", "segments", "zone", "goto",
                "fan_speed", "water_usage", "camera_light",
                "locate", "empty_dock", "mop_wash", "mop_dry", "restrictions",
                "rename_room", "join_rooms", "split_room")

# One-shot dock/robot commands: key -> (capability, payload).
SIMPLE_COMMANDS = {
    "locate": ("LocateCapability", {"action": "locate"}),
    "empty_dock": ("AutoEmptyDockManualTriggerCapability", {"action": "trigger"}),
    "mop_wash": ("MopDockCleanManualTriggerCapability", {"action": "start"}),
    "mop_dry": ("MopDockDryManualTriggerCapability", {"action": "start"}),
}

# On/off capabilities handled by fetch_toggle() / set_toggle(), with their command key.
TOGGLE_CAPABILITIES = {
    "CameraLightControlCapability": "camera_light",
}

# Preset capabilities handled by set_preset(), with their command key.
PRESET_CAPABILITIES = {
    "FanSpeedControlCapability": "fan_speed",
    "WaterUsageControlCapability": "water_usage",
    "OperationModeControlCapability": "operation_mode",
}


class ValetudoClient(QObject):
    robotInfoReceived = pyqtSignal(dict)
    versionReceived = pyqtSignal(dict)
    capabilitiesReceived = pyqtSignal(list)
    attributesReceived = pyqtSignal(list)
    mapReceived = pyqtSignal(dict)
    consumablesReceived = pyqtSignal(list)
    currentStatisticsReceived = pyqtSignal(list)
    totalStatisticsReceived = pyqtSignal(list)
    wifiReceived = pyqtSignal(dict)
    eventsReceived = pyqtSignal(list)
    presetsReceived = pyqtSignal(str, list)   # capability name, preset names
    toggleReceived = pyqtSignal(str, bool)     # capability name, enabled
    mapPeeked = pyqtSignal(dict)               # map read for the panel only (no layers)
    restrictionsReceived = pyqtSignal(dict)    # no-go zones and virtual walls
    segmentsReceived = pyqtSignal(list)        # rooms: [{"id": "16", "name": "Kitchen"}, …]
    hostInfoReceived = pyqtSignal(dict)        # system host info + "robot_time" (Unix s)
    timersReceived = pyqtSignal(list)          # Valetudo timers (dicts with their "id")
    timerPropertiesReceived = pyqtSignal(dict)  # supportedActions, supportedPreActions
    commandDone = pyqtSignal(str)
    reachable = pyqtSignal(bool)              # emitted after every request
    error = pyqtSignal(str)

    def __init__(self, base_url, authcfg="", parent=None):
        super().__init__(parent)
        self.base = base_url.rstrip("/") + "/api/v2"
        self.authcfg = authcfg  # QGIS authentication manager config id
        self.nam = QgsNetworkAccessManager.instance()
        self._replies = set()   # keeps replies alive until they finish
        self._map_pending = False
        self._peek_pending = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.fetch_map(quiet=True))

    # -- plumbing -----------------------------------------------------------

    def _request(self, path):
        req = QNetworkRequest(QUrl(self.base + path))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        if self.authcfg:
            res = QgsApplication.authManager().updateNetworkRequest(req, self.authcfg)
            if isinstance(res, tuple):  # depends on the PyQGIS version
                req = res[1]
        return req

    def _get(self, path, callback, on_finish=None, quiet=False):
        self._track(self.nam.get(self._request(path)), callback, on_finish, quiet)

    def _put(self, path, payload, callback=None):
        body = QByteArray(json.dumps(payload).encode())
        self._track(self.nam.put(self._request(path), body), callback)

    def _post(self, path, payload, callback=None):
        body = QByteArray(json.dumps(payload).encode())
        self._track(self.nam.post(self._request(path), body), callback)

    def _delete(self, path, callback=None):
        self._track(self.nam.deleteResource(self._request(path)), callback)

    def _track(self, reply, callback, on_finish=None, quiet=False, on_error=None, raw=False):
        """quiet=True: background request, failures only emit reachable(False).

        on_error(message) is called on failure; raw=True passes the body as text.
        """
        self._replies.add(reply)

        def finished():
            self._replies.discard(reply)
            try:
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    # A refused command (HTTP 4xx/5xx) still means the robot answered.
                    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                    self.reachable.emit(bool(status))
                    detail = self._error_detail(reply)
                    if on_error:
                        on_error(detail or reply.errorString())
                    if not quiet:
                        # errorString() is already localised by Qt; the robot's own
                        # message (e.g. why a split line was refused) is added if any.
                        text = f"{reply.url().toString()}: {reply.errorString()}"
                        self.error.emit(f"{text} — {detail}" if detail else text)
                    return
                self.reachable.emit(True)
                body = bytes(reply.readAll())
                if raw:
                    data = body.decode("utf-8", "replace")
                elif not body.strip():
                    data = None
                else:
                    try:
                        data = json.loads(body)
                    except ValueError:
                        # Commands answer plain text ("OK"), not JSON: that is a success.
                        data = body.decode("utf-8", "replace").strip()
                if callback:
                    callback(data)
            except Exception as exc:
                self.error.emit(f"{type(exc).__name__}: {exc}")
            finally:
                if on_finish:
                    on_finish()
                reply.deleteLater()

        reply.finished.connect(finished)

    @staticmethod
    def _error_detail(reply):
        """Short text body of an error reply (Valetudo explains refusals there)."""
        try:
            body = bytes(reply.readAll()).decode("utf-8", "replace").strip()
        except Exception:
            return ""
        if not body or body.startswith("<"):
            return ""
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                body = str(data.get("message") or data.get("error") or body)
        except ValueError:
            pass
        return body[:300]

    @staticmethod
    def _as_list(data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.values())
        return []

    # -- reading ------------------------------------------------------------

    def fetch_robot_info(self, quiet=False):
        self._get("/robot", lambda d: self.robotInfoReceived.emit(d or {}), quiet=quiet)

    def fetch_version(self, quiet=False):
        self._get("/valetudo/version", lambda d: self.versionReceived.emit(d or {}), quiet=quiet)

    def fetch_capabilities(self, quiet=False):
        self._get("/robot/capabilities",
                  lambda d: self.capabilitiesReceived.emit(self._as_list(d)), quiet=quiet)

    def fetch_attributes(self, quiet=False):
        """Status, battery, presets, attachments, dock status..."""
        self._get("/robot/state/attributes",
                  lambda d: self.attributesReceived.emit(self._as_list(d)), quiet=quiet)

    def fetch_consumables(self, quiet=False):
        self._get("/robot/capabilities/ConsumableMonitoringCapability",
                  lambda d: self.consumablesReceived.emit(self._as_list(d)), quiet=quiet)

    def fetch_current_statistics(self, quiet=False):
        self._get("/robot/capabilities/CurrentStatisticsCapability",
                  lambda d: self.currentStatisticsReceived.emit(self._as_list(d)), quiet=quiet)

    def fetch_total_statistics(self, quiet=False):
        self._get("/robot/capabilities/TotalStatisticsCapability",
                  lambda d: self.totalStatisticsReceived.emit(self._as_list(d)), quiet=quiet)

    def fetch_wifi(self, quiet=False):
        self._get("/robot/capabilities/WifiConfigurationCapability",
                  lambda d: self.wifiReceived.emit(d or {}), quiet=quiet)

    def fetch_events(self, quiet=False):
        self._get("/events", lambda d: self.eventsReceived.emit(self._as_list(d)), quiet=quiet)

    def fetch_host_info(self, quiet=True):
        """Host info (uptime, hostname…) plus the robot's own clock, read from the
        HTTP Date header of the answer: no SSH needed to know the robot's time."""
        reply = self.nam.get(self._request("/system/host/info"))

        def done(data):
            info = dict(data) if isinstance(data, dict) else {}
            stamp = bytes(reply.rawHeader(QByteArray(b"Date"))).decode("latin-1").strip()
            try:
                info["robot_time"] = email.utils.parsedate_to_datetime(stamp).timestamp()
                info["received_at"] = time.time()
            except (TypeError, ValueError, IndexError):
                pass
            self.hostInfoReceived.emit(info)

        # Without that endpoint (older Valetudo), the answer still has the robot's Date.
        self._track(reply, done, quiet=quiet, on_error=lambda _detail: done(None))

    def fetch_presets(self, capability, quiet=False):
        self._get(f"/robot/capabilities/{capability}/presets",
                  lambda d: self.presetsReceived.emit(capability, self._as_list(d)),
                  quiet=quiet)

    def fetch_toggle(self, capability, quiet=True):
        self._get(f"/robot/capabilities/{capability}",
                  lambda d: self.toggleReceived.emit(capability, bool((d or {}).get("enabled"))),
                  quiet=quiet)

    def probe(self, path, on_success, on_error, raw=False, timeout_ms=3000):
        """One-off GET with a short timeout, for the boot monitor (never pushes errors)."""
        req = self._request(path)
        if hasattr(req, "setTransferTimeout"):
            req.setTransferTimeout(timeout_ms)
        self._track(self.nam.get(req), on_success, quiet=True, on_error=on_error, raw=raw)

    def fetch_segments(self, quiet=True):
        self._get("/robot/capabilities/MapSegmentationCapability",
                  lambda d: self.segmentsReceived.emit(self._as_list(d)), quiet=quiet)

    def fetch_restrictions(self):
        self._get("/robot/capabilities/CombinedVirtualRestrictionsCapability",
                  lambda d: self.restrictionsReceived.emit(d or {}))

    def peek_map(self):
        """Read the map for the status panel (position) without touching the layers."""
        if self._peek_pending:
            return
        self._peek_pending = True
        self._get("/robot/state/map", self.mapPeeked.emit,
                  on_finish=lambda: setattr(self, "_peek_pending", False), quiet=True)

    def fetch_map(self, quiet=False):
        if self._map_pending:  # do not pile up requests if the robot is slow
            return
        self._map_pending = True
        self._get("/robot/state/map", self.mapReceived.emit,
                  on_finish=lambda: setattr(self, "_map_pending", False), quiet=quiet)

    def start_polling(self, interval_ms=2000):
        """Background map refresh: failures are reported through reachable() only."""
        self.fetch_map(quiet=True)
        self._timer.start(interval_ms)

    def stop_polling(self):
        self._timer.stop()

    def is_polling(self):
        return self._timer.isActive()

    # -- commands -----------------------------------------------------------

    def _command(self, capability, payload, key, path_suffix=""):
        self._put(f"/robot/capabilities/{capability}{path_suffix}", payload,
                  lambda _data: self.commandDone.emit(key))

    def set_restrictions(self, payload):
        """Replace all no-go zones and virtual walls on the robot."""
        self._command("CombinedVirtualRestrictionsCapability", payload, "restrictions")

    def simple_command(self, key):
        """Run a one-shot command from SIMPLE_COMMANDS (locate, empty dock, wash/dry mops)."""
        capability, payload = SIMPLE_COMMANDS[key]
        self._command(capability, payload, key)

    def basic_control(self, action):
        """action: 'start', 'stop', 'pause' or 'home'."""
        self._command("BasicControlCapability", {"action": action}, action)

    def set_preset(self, capability, name):
        """Select a preset (e.g. fan speed 'high') on a preset capability."""
        self._command(capability, {"name": name}, PRESET_CAPABILITIES.get(capability, capability),
                      path_suffix="/preset")

    def put_preset(self, capability, name, on_done=None, on_error=None):
        """Select a preset silently (no commandDone): for automatic changes."""
        body = QByteArray(json.dumps({"name": name}).encode())
        reply = self.nam.put(self._request(f"/robot/capabilities/{capability}/preset"), body)
        self._track(reply, lambda _data: on_done and on_done(), quiet=True, on_error=on_error)

    def set_toggle(self, capability, enabled):
        """Switch an on/off capability (e.g. the camera light)."""
        self._command(capability, {"action": "enable" if enabled else "disable"},
                      TOGGLE_CAPABILITIES.get(capability, capability))

    # -- timers (Valetudo's own schedule, run by the robot) -------------------------

    @staticmethod
    def _timers_list(data):
        """GET /timers: {id: timer, …} (possibly wrapped in "timers") -> [timer with id]."""
        if isinstance(data, dict) and isinstance(data.get("timers"), dict):
            data = data["timers"]
        if isinstance(data, dict):
            return [dict(timer, id=timer.get("id") or key) for key, timer in data.items()
                    if isinstance(timer, dict)]
        return [t for t in data if isinstance(t, dict)] if isinstance(data, list) else []

    def fetch_timers(self, quiet=True):
        self._get("/timers", lambda d: self.timersReceived.emit(self._timers_list(d)),
                  quiet=quiet)

    def fetch_timer_properties(self, quiet=True):
        self._get("/timers/properties",
                  lambda d: self.timerPropertiesReceived.emit(d if isinstance(d, dict) else {}),
                  quiet=quiet)

    TIMER_FIELDS = ("id", "enabled", "label", "dow", "hour", "minute", "action", "pre_actions")

    def save_timer(self, timer):
        """Create (no id) or replace (with id) a timer; the list is fetched again.

        Only the documented fields are sent: Valetudo refuses any other one."""
        timer = {k: v for k, v in timer.items() if k in self.TIMER_FIELDS}
        done = lambda _data: (self.commandDone.emit("timer_save"), self.fetch_timers())
        if timer.get("id"):
            self._put(f"/timers/{timer['id']}", timer, done)
        else:
            self._post("/timers", {k: v for k, v in timer.items() if k != "id"}, done)

    def delete_timer(self, timer_id):
        self._delete(f"/timers/{timer_id}",
                     lambda _data: (self.commandDone.emit("timer_delete"), self.fetch_timers()))

    def run_timer(self, timer_id):
        """Start a stored timer now, whatever its days and time."""
        self._put(f"/timers/{timer_id}/action", {"action": "execute_now"},
                  lambda _data: self.commandDone.emit("timer_run"))

    # -- room (segment) editing ----------------------------------------------------

    def rename_segment(self, segment_id, name):
        self._command("MapSegmentRenameCapability", {
            "action": "rename_segment", "segment_id": str(segment_id), "name": name,
        }, "rename_room")

    def join_segments(self, segment_a_id, segment_b_id):
        self._command("MapSegmentEditCapability", {
            "action": "join_segments",
            "segment_a_id": str(segment_a_id), "segment_b_id": str(segment_b_id),
        }, "join_rooms")

    def split_segment_qgis(self, segment_id, point_a, point_b):
        """Split a room along a line given in the QGIS frame (converted to map cm)."""
        (ax, ay), (bx, by) = q2v(point_a), q2v(point_b)
        self._command("MapSegmentEditCapability", {
            "action": "split_segment", "segment_id": str(segment_id),
            "pA": {"x": ax, "y": ay}, "pB": {"x": bx, "y": by},
        }, "split_room")

    def clean_segments(self, segment_ids, iterations=1):
        self._command("MapSegmentationCapability", {
            "action": "start_segment_action",
            "segment_ids": [str(s) for s in segment_ids],
            "iterations": iterations,
            "customOrder": False,
        }, "segments")

    def clean_zone_qgis(self, rect, iterations=1):
        """Clean a QgsRectangle expressed in the QGIS frame."""
        x1, y1 = q2v(QgsPointXY(rect.xMinimum(), rect.yMaximum()))  # top-left
        x2, y2 = q2v(QgsPointXY(rect.xMaximum(), rect.yMinimum()))  # bottom-right
        zone = {"points": {
            "pA": {"x": x1, "y": y1}, "pB": {"x": x2, "y": y1},
            "pC": {"x": x2, "y": y2}, "pD": {"x": x1, "y": y2},
        }}
        self._command("ZoneCleaningCapability",
                      {"action": "clean", "zones": [zone], "iterations": iterations},
                      "zone")

    def go_to_qgis(self, point):
        x, y = q2v(point)
        self._command("GoToLocationCapability",
                      {"action": "goto", "coordinates": {"x": x, "y": y}}, "goto")
