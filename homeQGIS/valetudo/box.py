"""Valetudo itself, in the Maintenance tab: its version, how long it has been
running, the robot's time sync, and its updates.

- GET /valetudo/version: release, commit.
- GET /system/runtime/info: uptime (s); phoenix.generation counts the times
  Valetudo restarted itself after a crash.
- GET /ntpclient/status: state (__class: …SyncedState with offset in ms,
  …ErrorState with message, …EnabledState, …DisabledState).
- GET /updater/state (__class: …IdleState, …NoUpdateRequiredState, …ApprovalPending
  with version and changelog, …DownloadingState, …ApplyPendingState, …ErrorState,
  …DisabledState; busy while checking). PUT /updater {action: check | download |
  apply}. "apply" installs the new Valetudo and restarts it: asked first.
"""

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QMessageBox,
                                 QPushButton, QWidget)

from qgis.gui import QgsCollapsibleGroupBox

from ..history.logic import format_duration
from ..core.i18n import tr

POLL_MS = 3000          # the updater's state, while it works
POLL_LIMIT = 40         # …at most this many times (2 minutes)


def updater_kind(state):
    """"idle", "no_update", "available", "downloading", "ready", "error", "disabled"."""
    name = str((state or {}).get("__class") or "")
    for marker, kind in (("NoUpdateRequired", "no_update"), ("ApprovalPending", "available"),
                         ("Downloading", "downloading"), ("ApplyPending", "ready"),
                         ("Error", "error"), ("Disabled", "disabled"), ("Idle", "idle")):
        if marker in name:
            return kind
    return "idle"


def ntp_text(status):
    state = (status or {}).get("state") or {}
    name = str(state.get("__class") or "")
    if "Synced" in name:
        offset = state.get("offset")
        return (tr("Synchronised (offset {ms} ms)").format(ms=int(offset))
                if isinstance(offset, (int, float)) else tr("Synchronised"))
    if "Error" in name:
        return tr("Error: {message}").format(message=state.get("message") or "?")
    if "Disabled" in name:
        return tr("Off (the robot's own clock)")
    return tr("Waiting for the first synchronisation")


class ValetudoBox(QgsCollapsibleGroupBox):
    def __init__(self, parent=None):
        super().__init__(tr("Valetudo"), parent)
        self.client = None
        form = QFormLayout(self)
        self.lbl_version, self.lbl_uptime, self.lbl_ntp = QLabel("…"), QLabel("…"), QLabel("…")
        for label in (self.lbl_version, self.lbl_uptime, self.lbl_ntp):
            label.setWordWrap(True)
        form.addRow(tr("Version"), self.lbl_version)
        form.addRow(tr("Running for"), self.lbl_uptime)
        form.addRow(tr("Time sync"), self.lbl_ntp)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.lbl_update = QLabel("…")
        self.lbl_update.setWordWrap(True)
        self.btn_update = QPushButton()
        self.btn_update.setVisible(False)
        self.btn_update.clicked.connect(self._update_action)
        line.addWidget(self.lbl_update, 1)
        line.addWidget(self.btn_update)
        form.addRow(tr("Updates"), row)
        self._state = {}
        self._polls = 0
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_state)

    def set_client(self, client):
        self.client = client
        self._poll.stop()

    def load(self):
        if self.client is None or not self.isVisible():
            return
        self.client.get_json("/valetudo/version", self._show_version)
        self.client.get_json("/system/runtime/info", self._show_runtime)
        self.client.get_json("/ntpclient/status", lambda d: self.lbl_ntp.setText(ntp_text(d)),
                             lambda e: self.lbl_ntp.setText(tr("Unknown")))
        self.client.get_json("/updater/state", self._show_updater,
                             lambda e: self.lbl_update.setText(tr("Unknown")))

    # -- showing ---------------------------------------------------------------------

    def _show_version(self, data):
        data = data or {}
        release, commit = data.get("release") or "?", str(data.get("commit") or "")[:8]
        self.lbl_version.setText(f"{release} ({commit})" if commit else release)

    def _show_runtime(self, data):
        data = data or {}
        seconds = int(data.get("uptime") or 0)
        text = (tr("{n} days").format(n=seconds // 86400) if seconds >= 2 * 86400
                else format_duration(seconds))
        restarts = ((data.get("phoenix") or {}).get("generation") or 0)
        if restarts:
            text += " · " + tr("restarted itself {n} time(s) after a problem").format(n=restarts)
        self.lbl_uptime.setText(text)

    def _show_updater(self, state):
        self._state = state or {}
        kind = updater_kind(self._state)
        version = self._state.get("version") or self._state.get("currentVersion") or ""
        texts = {
            "idle": (tr("Not checked yet"), tr("Check for updates")),
            "no_update": (tr("Up to date"), tr("Check again")),
            "available": (tr("Version {v} available").format(v=version), tr("Download")),
            "downloading": (tr("Downloading version {v}…").format(v=version), None),
            "ready": (tr("Version {v} downloaded").format(v=version), tr("Install…")),
            "error": (tr("Error: {m}").format(m=self._state.get("message") or "?"),
                      tr("Check again")),
            "disabled": (tr("Off in Valetudo's settings"), None),
        }
        text, button = texts[kind]
        if self._state.get("busy"):
            text, button = tr("Checking…"), None
        self.lbl_update.setText(text)
        self.lbl_update.setToolTip(str(self._state.get("changelog") or ""))
        self.btn_update.setVisible(button is not None)
        if button:
            self.btn_update.setText(button)
        if not (self._state.get("busy") or kind == "downloading"):
            self._poll.stop()

    # -- updating ------------------------------------------------------------------------

    def _update_action(self):
        kind = updater_kind(self._state)
        if kind == "available":
            action = "download"
        elif kind == "ready":
            answer = QMessageBox.question(
                self, tr("Update Valetudo"),
                tr("Install Valetudo {v} on the robot? Valetudo restarts: the robot is "
                   "unreachable for a minute or so. Do not do it during a cleaning.").format(
                    v=self._state.get("version") or ""))
            if answer != QMessageBox.StandardButton.Yes:
                return
            action = "apply"
        else:
            action = "check"
        self.btn_update.setVisible(False)
        self.lbl_update.setText(tr("Asked…"))
        self.client.put_json("/updater", {"action": action}, self._follow,
                             lambda e: self.lbl_update.setText(tr("Error: {m}").format(m=e)))

    def _follow(self, *_):
        self._polls = 0
        self._poll.start()

    def _poll_state(self):
        self._polls += 1
        if self.client is None or self._polls > POLL_LIMIT:
            self._poll.stop()
            return
        self.client.get_json("/updater/state", self._show_updater)
