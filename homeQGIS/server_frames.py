"""One frame per server of the settings in the Status tab, kept up to date by a
block of its type:

    rpi, linux   ssh_host_block.SshHostBlock (name, system, clock, uptime, resources)
    ha           ha_block.HaBlock
    kodi         kodi_block.KodiBlock (and what is playing)
    windows      PortBlock: its SSH, RDP or VNC port answers or not
    web          WebBlock: its address answers or not

    ┌ (logo) NUC   ● Connected · updated 3 s ago        [⏻] [🌐] [🖥] [>_] ┐
    │ nuc · Linux 6.1 …                                                   │
    │ 192.168.50.2 · 20/11/2026 20:32 · up 3 d 2 h                        │
    │ load 0.4 / 4 CPUs · RAM 3.1 / 15 GB · disk 120 / 450 GB · 45 °C     │
    └─────────────────────────────────────────────────────────────────────┘

Each block has ok (True, False, None before the first answer), strip_state()
("on", "off", "connecting", "no_token"), update(panel_visible), refresh(),
render() (every second) and stop().
"""

import time

from qgis.PyQt.QtCore import QObject, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest, QTcpSocket
from qgis.PyQt.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QSizePolicy,
                                 QToolButton, QVBoxLayout, QWidget)
from qgis.core import QgsNetworkAccessManager

from .i18n import tr

POLL_MS = 60_000


def _dot(color, text):
    return f"<span style='color:{color}'>●</span> {text}"


class ServerFrame(QFrame):
    """The widgets of a server's frame (built in code, like the robot's in the .ui)."""

    def __init__(self, title, logo_pixmap, kind, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        row = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setPixmap(logo_pixmap)
        self.title = QLabel(title)
        font = QFont(self.title.font())
        font.setBold(True)
        self.title.setFont(font)
        self.connection = QLabel()
        self.connection.setTextFormat(Qt.TextFormat.RichText)
        self.btn_wake = QToolButton()   # Wake-on-LAN
        self.btn_web, self.btn_rd, self.btn_ssh = QToolButton(), QToolButton(), QToolButton()
        row.addWidget(self.logo)
        row.addWidget(self.title)
        row.addWidget(self.connection, 1)
        for button in (self.btn_wake, self.btn_web, self.btn_rd, self.btn_ssh):
            button.setAutoRaise(True)
            button.setVisible(False)
            row.addWidget(button)
        layout.addLayout(row)
        self.name, self.info, self.resources = QLabel(), QLabel(), QLabel()
        for label in (self.name, self.info, self.resources):
            label.setWordWrap(True)
            layout.addWidget(label)
        self.name.setFont(_italic(self.name.font()))
        self.resources.setVisible(False)
        self.widgets = {"header": self, "connection": self.connection, "name": self.name,
                        "info": self.info, "resources": self.resources}
        if kind == "kodi":   # what is playing: ▶ title · time [progress] [⏸] [⏹]
            self.play_row = QWidget()
            play = QHBoxLayout(self.play_row)
            play.setContentsMargins(0, 0, 0, 0)
            self.playing = QLabel()
            self.playing.setWordWrap(True)
            self.progress = QProgressBar()
            self.progress.setMaximumWidth(90)
            self.progress.setMaximumHeight(12)
            self.progress.setTextVisible(False)
            self.btn_play, self.btn_stop = QToolButton(), QToolButton()
            self.btn_play.setText("⏸")
            self.btn_stop.setText("⏹")
            self.btn_stop.setToolTip(tr("Stop"))
            play.addWidget(self.playing, 1)
            for widget in (self.progress, self.btn_play, self.btn_stop):
                play.addWidget(widget)
            layout.addWidget(self.play_row)
            self.widgets.update(play_row=self.play_row, playing=self.playing,
                                progress=self.progress, play=self.btn_play, stop=self.btn_stop)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)


def _italic(font):
    font = QFont(font)
    font.setItalic(True)
    return font


class WebBlock(QObject):
    """A web service: does its address answer? (any HTTP status counts)"""

    def __init__(self, widgets, url, parent=None):
        super().__init__(parent)
        self.w, self._url = widgets, url
        self.ok, self.last_ok, self.status, self.error = None, None, None, ""
        self._reply = None
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.refresh)

    def strip_state(self):
        return {True: "on", False: "off", None: "connecting"}[self.ok]

    def tooltip(self):
        return self.error if self.ok is False else self._url()

    def update(self, panel_visible):
        if panel_visible:
            if not self.timer.isActive():
                self.timer.start()
                self.refresh()
        else:
            self.timer.stop()

    def stop(self):
        self.timer.stop()

    def refresh(self, *_):
        url = self._url()
        if not url or self._reply is not None:
            return
        qurl = QUrl(url if "://" in url else "http://" + url)
        if qurl.scheme().lower() not in ("http", "https"):   # not checked over the web
            self.ok, self.error = False, f"{qurl.scheme()}: not a web address (http, https)"
            self.render()
            return
        request = QNetworkRequest(qurl)
        request.setTransferTimeout(8000)
        reply = self._reply = QgsNetworkAccessManager.instance().get(request)

        def done():
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            self._reply = None
            if reply.error() == QNetworkReply.NetworkError.NoError or status:
                self.ok, self.last_ok, self.status = True, time.monotonic(), status
            else:
                self.ok, self.error = False, reply.errorString()
            reply.deleteLater()
            self.render()
        reply.finished.connect(done)

    def render(self):
        if self.ok is None:
            self.w["connection"].setText(_dot("#9e9e9e", tr("Connecting…")))
        elif self.ok:
            self.w["connection"].setText(_dot("#2e7d32", tr(
                "Answers (HTTP {status}) · checked {seconds} s ago").format(
                    status=self.status or "?",
                    seconds=int(time.monotonic() - self.last_ok))))
        else:
            self.w["connection"].setText(_dot("#c62828", tr("Unreachable")))
        self.w["connection"].setToolTip(self.error if self.ok is False else "")
        self.w["name"].setVisible(False)
        self.w["info"].setText(self._url())


class PortBlock(QObject):
    """A computer that is not read over SSH (Windows): does one of its ports answer?"""

    def __init__(self, widgets, target, parent=None):
        """target(): (host, port, what) or None, what naming the port (SSH, RDP…)."""
        super().__init__(parent)
        self.w, self._target = widgets, target
        self.ok, self.last_ok, self.error = None, None, ""
        self._socket = None
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS // 2)
        self.timer.timeout.connect(self.refresh)

    def strip_state(self):
        return {True: "on", False: "off", None: "connecting"}[self.ok]

    def tooltip(self):
        target = self._target()
        return f"{target[2]} {target[0]}:{target[1]}" if target else ""

    def update(self, panel_visible):
        if panel_visible and self._target() is not None:
            if not self.timer.isActive():
                self.timer.start()
                self.refresh()
        else:
            self.timer.stop()

    def stop(self):
        self.timer.stop()
        if self._socket is not None:
            self._socket.abort()

    def refresh(self, *_):
        target = self._target()
        if target is None or self._socket is not None:
            return
        sock = self._socket = QTcpSocket(self)
        timeout = QTimer(sock)
        timeout.setSingleShot(True)

        def finish(ok, error=""):
            if self._socket is not sock:
                return
            self._socket = None
            timeout.stop()
            self.ok, self.error = ok, error
            if ok:
                self.last_ok = time.monotonic()
            sock.abort()
            sock.deleteLater()
            self.render()
        sock.connected.connect(lambda: finish(True))
        sock.errorOccurred.connect(lambda *_: finish(False, sock.errorString()))
        timeout.timeout.connect(lambda: finish(False, tr("no answer")))
        timeout.start(5000)
        sock.connectToHost(target[0], int(target[1]))

    def render(self):
        target = self._target()
        what = f"{target[2]} {target[0]}:{target[1]}" if target else ""
        if self.ok is None:
            text = _dot("#9e9e9e", tr("Connecting…"))
        elif self.ok:
            text = _dot("#2e7d32", tr("{what} answers · checked {seconds} s ago").format(
                what=target[2] if target else "", seconds=int(time.monotonic() - self.last_ok)))
        else:
            text = _dot("#c62828", tr("Unreachable"))
        self.w["connection"].setText(text)
        self.w["connection"].setToolTip(self.error if self.ok is False else "")
        self.w["name"].setVisible(False)
        self.w["info"].setText(what)


# -- Terminal tab pages for a server (as the robot's, from the .ui) ---------------------

def _mono_text():
    from qgis.PyQt.QtGui import QFontDatabase
    from qgis.PyQt.QtWidgets import QPlainTextEdit
    text = QPlainTextEdit()
    text.setReadOnly(True)
    text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    text.setMaximumBlockCount(5000)
    text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    return text


def build_console_page(tooltip):
    """A console page: (page, widgets for console_tab.ConsoleTab)."""
    from qgis.PyQt.QtWidgets import QLineEdit
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    header = QHBoxLayout()
    w = {"status": QLabel(), "connect": QToolButton(), "clear": QToolButton(),
         "output": _mono_text(), "prompt": QLabel("$"), "edit": QLineEdit(),
         "run": QToolButton(), "stop": QToolButton()}
    w["status"].setWordWrap(True)
    w["connect"].setText(tr("Connect"))
    w["clear"].setText(tr("Clear"))
    header.addWidget(w["status"], 1)
    header.addWidget(w["connect"])
    header.addWidget(w["clear"])
    layout.addLayout(header)
    layout.addWidget(w["output"], 1)
    row = QHBoxLayout()
    w["edit"].setPlaceholderText(tr("Command, then Enter (↑ ↓: history)"))
    w["edit"].setToolTip(tooltip)
    w["run"].setText(tr("Run"))
    w["stop"].setText(tr("Stop"))
    w["stop"].setToolTip(tr("Stop the running command (reconnects)."))
    row.addWidget(w["prompt"])
    row.addWidget(w["edit"], 1)
    row.addWidget(w["run"])
    row.addWidget(w["stop"])
    layout.addLayout(row)
    return page, w


def build_log_page():
    """A log page: (page, widgets for log_tab.LogTab)."""
    from qgis.PyQt.QtWidgets import QCheckBox
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    header = QHBoxLayout()
    w = {"status": QLabel(), "follow": QCheckBox(tr("Scroll to new lines")),
         "clear": QToolButton(), "output": _mono_text()}
    w["status"].setWordWrap(True)
    w["follow"].setChecked(True)
    w["clear"].setText(tr("Clear"))
    header.addWidget(w["status"], 1)
    header.addWidget(w["follow"])
    header.addWidget(w["clear"])
    layout.addLayout(header)
    layout.addWidget(w["output"], 1)
    return page, w
