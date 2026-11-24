"""Home Assistant, as a block of the Status tab:

    (logo) Home Assistant  ● Connected · updated 5 s ago
    Home Assistant 2026.11.2 · Maison · Europe/Paris
    192.168.50.2 · 20/11/2026 20:32 · up 3 d 2 h

One GET /api/config every minute while the panel is visible. Without a token,
Home Assistant only says it is there (401): shown as "No token".
"""

import time

from qgis.PyQt.QtCore import QDateTime, QObject, Qt, QTimer, QUrl

from ..servers import host_info
from .ha_client import UNAUTHORISED, HomeAssistantClient, parse_timestamp
from ..core.i18n import tr

INTERVAL_MS = 60_000


class HaBlock(QObject):
    def __init__(self, widgets, url, token, local_time, parent=None):
        """widgets: dict connection, name, info (QLabels); url(): its address;
        token(): its access token ("" if none; read once, may ask for the master
        password); local_time(epoch) -> text."""
        super().__init__(parent)
        self.w = widgets
        self._url, self._token_source = url, token
        self._local_time = local_time
        self._token = None
        self._client = None
        self.state = None          # None, "connecting", "online", "no_token", "offline"
        self.info = {}             # url, name, version, time zone, clock, start, error
        self.last_ok = None
        self.last_ok_clock = ""
        self.timer = QTimer(self)
        self.timer.setInterval(INTERVAL_MS)
        self.timer.timeout.connect(self.refresh)

    @property
    def ok(self):
        return {"online": True, "no_token": True, "offline": False}.get(self.state)

    def strip_state(self):
        return {"online": "on", "offline": "off", None: "connecting"}.get(self.state, self.state)

    def update(self, panel_visible):
        if panel_visible:
            if not self.timer.isActive():
                self.timer.start()
                self.refresh()
        else:
            self.timer.stop()

    def stop(self):
        self.timer.stop()
        if self._client is not None:
            self._client.close()

    def refresh(self, *_):
        url = self._url()
        if not url:
            return
        if self._token is None:
            self._token = self._token_source() or ""
        if self._client is not None:
            self._client.close()
        client = self._client = HomeAssistantClient(url, self._token, self)
        self.info["url"] = url
        if self.state is None:
            self.state = "connecting"
            self.render()

        def ok(config):
            config = config if isinstance(config, dict) else {}
            self.info.update(name=config.get("location_name") or "",
                             version=config.get("version") or "",
                             time_zone=config.get("time_zone") or "",
                             time=client.server_time, received_at=client.received_at, error="")
            self.state = "online"
            self.last_ok = time.monotonic()
            self.last_ok_clock = QDateTime.currentDateTime().toString("HH:mm:ss")
            self.render()
            # Uptime: the "Uptime" integration's sensor (its state is the start time)
            client.get("/states/sensor.uptime", uptime_ok,
                       lambda _error: self._set_start(None), timeout_ms=5000)

        def uptime_ok(state):
            self._set_start(parse_timestamp(state.get("state")) if isinstance(state, dict)
                            else None)

        def failed(error):
            self.info["error"] = error
            self.state = "no_token" if error == UNAUTHORISED else "offline"
            self.render()

        client.get("/config", ok, failed, timeout_ms=5000)

    def _set_start(self, start):
        self.info["start"] = start
        self.render()

    def tooltip(self):
        if self.state == "offline":
            return self.info.get("error", "")
        return " · ".join(p for p in (self.info.get("name"), self.info.get("version"),
                                      self.info.get("url")) if p)

    def render(self):
        """Also called every second by the panel ("updated N s ago")."""
        state, ha = self.state, self.info
        if state is None:
            return
        if state == "connecting":
            color, text = "#9e9e9e", tr("Connecting…")
        elif state == "online":
            color = "#2e7d32"
            text = tr("Connected · updated {seconds} s ago").format(
                seconds=int(time.monotonic() - self.last_ok))
        elif state == "no_token":
            color, text = "#ef6c00", tr("Found, no access token")
        else:
            color = "#c62828"
            text = tr("Unreachable · last update {time}").format(time=self.last_ok_clock or "—")
        self.w["connection"].setText(f"<span style='color:{color}'>●</span> {text}")
        self.w["connection"].setToolTip(ha.get("error", "") if state == "offline" else "")
        url = ha.get("url", "")
        if state == "no_token":
            name = tr("Home Assistant answers at {url}. Add an access token in the settings "
                      "(Servers tab) to use it.").format(url=url)
        else:
            version = ha.get("version", "")
            name = " · ".join(p for p in (
                f"Home Assistant {version}" if version else "Home Assistant",
                ha.get("name"), ha.get("time_zone")) if p)
        self.w["name"].setTextFormat(Qt.TextFormat.PlainText)
        self.w["name"].setText(name)
        host = QUrl(url).host() or url
        online = state == "online"
        uptime = None
        if online and ha.get("start") and ha.get("time"):
            uptime = max(0, ha["time"] - ha["start"])
        line, wrong = host_info.info_line(host, ha.get("time") if online else None,
                                          ha.get("received_at"), uptime, self._local_time)
        self.w["info"].setText(line)
        self.w["info"].setStyleSheet("color: #ef6c00;" if wrong else "")
