"""About: what the plugin does, its links, and the system it runs on.

One widget (AboutWidget), shown in the settings (tab About) and in a window
from the panel's ⋮ menu (AboutDialog). Name, version, author, licence and
links come from metadata.txt.
"""

import configparser
import html
import os
import platform
import shutil
import subprocess

from qgis.PyQt.QtCore import QT_VERSION_STR, Qt
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                                 QLabel, QPushButton, QScrollArea, QToolButton, QVBoxLayout,
                                 QWidget)
from qgis.core import Qgis

from .camera import find_ffmpeg
from .i18n import tr
from .icons import APP_ICON, icon
from .settings import PLUGIN_NAME, load_settings

VALETUDO_URL = "https://valetudo.cloud"


def metadata():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(os.path.join(os.path.dirname(__file__), "metadata.txt"), encoding="utf-8")
    return dict(parser["general"]) if parser.has_section("general") else {}


def sections():
    """(title, [lines]) of what the plugin does: robot, home, servers, settings."""
    return [
        (tr("Robot: map"), [
            tr("Floor, walls, rooms, robot, dock, path and planned path as QGIS layers"),
            tr("Live tracking, optionally keeping the robot in view; status card on the map"),
            tr("Its own QGIS project, opened with the map when QGIS starts, if asked"),
        ]),
        (tr("Robot: cleaning"), [
            tr("All rooms, ticked rooms, room groups, a zone drawn on the map, 1 to 3 passes"),
            tr("Cleaning profile: mode, water usage, fan speed"),
            tr("Rooms picked on the map; Go to, also on robots without it, with or "
               "without cleaning"),
            tr("Start, pause, resume, back to the dock"),
        ]),
        (tr("Robot: rooms and restrictions"), [
            tr("Rename, join and split rooms"),
            tr("No-go zones, no-mop zones and virtual walls edited with the QGIS tools "
               "and sent to the robot"),
        ]),
        (tr("Robot: schedule"), [
            tr("Valetudo's timers in a week view; drag rooms onto it to create one"),
            tr("A cleaning profile per timer, run now, one-off cleanings for tonight"),
        ]),
        (tr("Robot: Wi-Fi"), [
            tr("Signal now and over the last 10 minutes"),
            tr("Survey recorded in QGIS, or on the robot itself while QGIS is closed"),
            tr("Interpolated signal maps, per run and cumulative ones built on a Raspberry Pi"),
        ]),
        (tr("Robot: camera"), [
            tr("Live view, full screen, snapshots, MP4 recording, camera light"),
        ]),
        (tr("Robot: care and system"), [
            tr("Consumables, dock station (empty the bin, wash and dry the mops), "
               "tank and bag warnings, statistics, robot settings, events"),
            tr("Reboot over SSH, boot watch with Valetudo's log, clock check"),
            tr("SSH console and live log on the robot"),
        ]),
        (tr("Home"), [
            tr("Home Assistant devices by room, with their state and a sparkline"),
            tr("History charts by period, comparison, battery trend, CSV and GeoPackage export"),
            tr("Sensor history replayed on the map with the Temporal Controller"),
        ]),
        (tr("Servers"), [
            tr("Any number of servers: Valetudo robots, Raspberry Pi, Home Assistant, "
               "Kodi, Linux and Windows computers, web services"),
            tr("Status: system, clock, uptime, load, memory, disk, temperature"),
            tr("SSH console and live log, by key or password"),
            tr("Remote desktop over VNC or RDP, through an SSH tunnel if needed"),
            tr("Kodi: what is playing, with its progress; play, pause and stop"),
            tr("On the air or off the air at a glance on the status line"),
        ]),
        (tr("Settings"), [
            tr("One Options page for all of them, with a test button for each server"),
            tr("Order of the panels and buttons of the toolbar chosen in the UI configuration"),
            tr("Tokens and passwords kept encrypted"),
            tr("Timestamped backups of the configuration, reset"),
            tr("English and French"),
        ]),
    ]


def _version(program, *args):
    """First line of `program args` (ssh prints its version on stderr), or ""."""
    try:
        result = subprocess.run([program, *args], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0].strip() if lines else ""


def system_lines():
    """[(name, value, ok)] of the system: ok None = informative only."""
    lines = [("QGIS", Qgis.version(), None), ("Qt", QT_VERSION_STR, None),
             ("Python", platform.python_version(), None),
             (tr("System"), platform.platform(terse=True), None)]
    ffmpeg = find_ffmpeg(load_settings().get("ffmpeg", ""))
    text = _version(ffmpeg, "-hide_banner", "-version") if ffmpeg else ""
    words = text.split()   # "ffmpeg version 6.1.1-3ubuntu5 Copyright…"
    number = words[2] if len(words) > 2 and words[1] == "version" else " ".join(words[:3])
    lines.append(("ffmpeg", number if text else tr("not found (camera)"),
                  bool(ffmpeg)))
    ssh = shutil.which("ssh")
    text = _version(ssh, "-V") if ssh else ""
    lines.append(("ssh", text.split(",")[0] if text else tr("not found (terminal, reboot)"),
                  bool(ssh)))
    return lines


class AboutWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        meta = metadata()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)

        # Header: logo, name, version
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icon(APP_ICON).pixmap(48, 48))
        header.addWidget(logo)
        title = QLabel(f"<b style='font-size:16pt'>{PLUGIN_NAME}</b>"
                       f"&nbsp;&nbsp;{html.escape(meta.get('version', ''))}")
        header.addWidget(title, 1)
        layout.addLayout(header)
        intro = QLabel(tr(
            "A control centre in QGIS for a robot vacuum running Valetudo, with its map "
            "as real GIS layers, for the Home Assistant devices of the home, and for the "
            "servers around them."))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # What it does: foldable sections
        self.sections = []
        for heading, lines in sections():
            button = QToolButton()
            button.setText(heading)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setArrowType(Qt.ArrowType.RightArrow)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setStyleSheet("QToolButton { font-weight: bold; border: none; }")
            text = QLabel("<ul style='margin-top:0; margin-bottom:4px'>" + "".join(
                f"<li>{html.escape(line)}</li>" for line in lines) + "</ul>")
            text.setWordWrap(True)
            text.setVisible(False)
            button.toggled.connect(lambda on, b=button, t=text: (
                t.setVisible(on),
                b.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)))
            layout.addWidget(button)
            layout.addWidget(text)
            self.sections.append((button, text))
        unfold = QPushButton(tr("Unfold all"))
        unfold.clicked.connect(self._toggle_all)
        self._unfold = unfold
        row = QHBoxLayout()
        row.addWidget(unfold)
        row.addStretch(1)
        layout.addLayout(row)

        # Links, author, licence (metadata.txt)
        homepage = meta.get("homepage", "")
        tracker = meta.get("tracker", "")
        links = [f"<a href='{html.escape(homepage)}'>{tr('Documentation and source code')}</a>"
                 if homepage else "",
                 f"<a href='{html.escape(tracker)}'>{tr('Report a problem')}</a>" if tracker else "",
                 f"<a href='{VALETUDO_URL}'>Valetudo</a>"]
        author = html.escape(meta.get("author", ""))
        email = meta.get("email", "")
        if email:
            author = f"<a href='mailto:{html.escape(email)}'>{author}</a>"
        licence = html.escape(meta.get("license", ""))
        if licence and homepage:
            licence = f"<a href='{html.escape(homepage)}/blob/main/LICENSE'>{licence}</a>"
        info = QLabel(" · ".join(p for p in links if p) + "<br>"
                      + tr("Author: {author} · Licence: {licence}").format(
                          author=author, licence=licence))
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        # System, for troubleshooting
        self._system = system_lines()
        system = QLabel(" · ".join(
            f"{html.escape(name)} {html.escape(value)}"
            + ("" if ok is None else (" ✓" if ok else " <span style='color:#c62828'>✗</span>"))
            for name, value, ok in self._system))
        system.setWordWrap(True)
        system.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(system)
        copy = QPushButton(tr("Copy system information"))
        copy.clicked.connect(self._copy)
        self._copy_button = copy
        row = QHBoxLayout()
        row.addWidget(copy)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

    def _toggle_all(self):
        unfold = not all(button.isChecked() for button, _ in self.sections)
        for button, _ in self.sections:
            button.setChecked(unfold)
        self._unfold.setText(tr("Fold all") if unfold else tr("Unfold all"))

    def system_text(self):
        meta = metadata()
        lines = [f"{PLUGIN_NAME} {meta.get('version', '')}"]
        lines += [f"{name}: {value}" for name, value, _ in self._system]
        return "\n".join(lines)

    def _copy(self):
        QApplication.clipboard().setText(self.system_text())
        self._copy_button.setText(tr("Copied"))


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("About {name}").format(name=PLUGIN_NAME))
        self.setWindowIcon(icon(APP_ICON))
        layout = QVBoxLayout(self)
        layout.addWidget(AboutWidget(self))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(560, 640)
