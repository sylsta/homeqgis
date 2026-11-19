"""A server read over SSH, shown as a block of the Status tab (the NUC):

    (logo) ● Connected · updated 5 s ago                      [⟳]
    nuc · Linux nuc 6.6.0 … x86_64 GNU/Linux
    192.168.50.2 · 18/11/2026 21:02 · up 2 d 3 h
    load 0.42 / 4 CPUs · RAM 2.1 / 7.7 GB · disk 25 / 110 GB · 42 °C

One short SSH command (host_info.SERVER_COMMAND) every interval while the
panel is visible. Key login only, like the Raspberry Pi.
"""

import time

from qgis.PyQt.QtCore import QObject, Qt, QTimer

from . import host_info
from .i18n import tr
from .robot_survey import RobotSurvey

INTERVAL_MS = 30_000


class SshHostBlock(QObject):
    def __init__(self, widgets, target, local_time, on_clock, parent=None):
        """widgets: dict header, connection, name, info, resources (QLabels
        and the header widget); target(): (host, user, port) or None;
        local_time(epoch) -> text; on_clock(wrong): called after each read."""
        super().__init__(parent)
        self.w = widgets
        self._target = target
        self._local_time = local_time
        self._on_clock = on_clock
        self.info = None          # host_info.parse_pi + resources, None = never read
        self.ok = None            # True / False after a read, None before
        self.last_ok = None       # time.monotonic() of the last successful read
        self.runner = RobotSurvey(self)
        self.runner.finished.connect(self._on_info)
        self.timer = QTimer(self)
        self.timer.setInterval(INTERVAL_MS)
        self.timer.timeout.connect(self.refresh)
        self.w["header"].setVisible(False)

    def update(self, panel_visible):
        """Show the block only when an address is set; read it while visible."""
        target = self._target()
        self.w["header"].setVisible(target is not None)
        if target is not None and panel_visible:
            if not self.timer.isActive():
                self.timer.start()
                self.refresh()
        else:
            self.timer.stop()
            self.runner.stop()
        if target is None:
            self.info, self.ok, self.last_ok = None, None, None
            self._on_clock(False)

    def stop(self):
        self.timer.stop()
        self.runner.stop()

    def refresh(self, *_):
        target = self._target()
        if target is None or self.runner.is_busy():
            return
        self.runner.run("host_info", *target, host_info.SERVER_COMMAND)
        if self.ok is None:
            self.w["connection"].setText(
                f"<span style='color:#9e9e9e'>●</span> {tr('Connecting…')}")

    def _on_info(self, _operation, ok, output, detail):
        if ok:
            self.info = host_info.parse_pi(output, time.time())
            self.info.update(host_info.parse_resources(output))
            self.ok, self.last_ok = True, time.monotonic()
            self.w["connection"].setToolTip("")
        else:
            self.ok = False
            self.w["connection"].setToolTip(detail)
        self.render()

    def render(self):
        """Also called every second by the panel ("updated N s ago")."""
        if self.ok is None:
            return
        if self.ok:
            text = tr("Connected · updated {seconds} s ago").format(
                seconds=int(time.monotonic() - self.last_ok))
            self.w["connection"].setText(f"<span style='color:#2e7d32'>●</span> {text}")
        else:
            self.w["connection"].setText(
                f"<span style='color:#c62828'>●</span> {tr('Unreachable over SSH')}")
        info = self.info or {}
        self.w["name"].setTextFormat(Qt.TextFormat.PlainText)
        self.w["name"].setText(" · ".join(
            p for p in (info.get("hostname"), info.get("uname")) if p))
        # Offline: its last clock, uptime and resources are no longer true
        online = bool(self.ok)
        line, wrong = host_info.info_line(info.get("ip") or (self._target() or [""])[0],
                                          info.get("time") if online else None,
                                          info.get("received_at"),
                                          info.get("uptime") if online else None,
                                          self._local_time)
        self.w["info"].setText(line)
        self.w["info"].setStyleSheet("color: #ef6c00;" if wrong else "")
        resources = host_info.resources_line(info) if online else ""
        self.w["resources"].setText(resources)
        self.w["resources"].setVisible(bool(resources))
        self._on_clock(wrong)
