"""Kodi, as a block of the Status tab:

    (logo) ● Connected · updated 3 s ago                         [⟳]
    Kodi 21.1 · Linux (MX 23.4 …)
    192.168.50.2 · up 2 days, 3 hours · CPU 48 °C
    ▶ The Big Lebowski (1998) · 01:12:40 / 01:57:00  [████▱▱ 62 %] [⏸] [⏹]

Read over Kodi's JSON-RPC while the panel is visible: the player every 5 s
(its time runs on locally in between), the system labels every 30 s.
"""

import time

from qgis.PyQt.QtCore import QObject, Qt, QTimer, QUrl

from ..core.i18n import tr
from .kodi_client import (INFO_LABELS, ITEM_PROPERTIES, PLAYER_PROPERTIES, KodiClient,
                          clock, item_title, rpc_url, seconds)

POLL_MS = 5_000
LABELS_EVERY = 6          # polls: the system labels every 30 s


class KodiBlock(QObject):
    def __init__(self, widgets, settings, parent=None):
        """widgets: dict header, connection, name, info, play_row, playing,
        progress, play, stop; settings(): (url, user, password) or None."""
        super().__init__(parent)
        self.w = widgets
        self._settings = settings
        self._client = None
        self._for = None          # settings the client was made with
        self.ok = None            # True / False after a poll, None before
        self.error = ""
        self.last_ok = None       # time.monotonic() of the last answer
        self.version = ""
        self.labels = {}
        self.player = None        # dict id, type, title, time, total, speed, at
        self._polls = 0
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.refresh)
        self.w["play"].clicked.connect(self.play_pause)
        self.w["stop"].clicked.connect(self.stop_playback)
        self.w["header"].setVisible(False)

    # -- life cycle ----------------------------------------------------------------

    def update(self, panel_visible):
        """Show the block only when an address is set; poll it while visible."""
        cfg = self._settings()
        self.w["header"].setVisible(cfg is not None)
        if cfg != self._for:   # new address or login: start afresh
            self._reset()
            self._for = cfg
        if cfg is not None and panel_visible:
            if not self.timer.isActive():
                self.timer.start()
                self.refresh()
        else:
            self.timer.stop()

    def strip_state(self):
        return {True: "on", False: "off", None: "connecting"}[self.ok]

    def tooltip(self):
        return self.error if self.ok is False else self._host()

    def stop(self):
        self.timer.stop()
        if self._client is not None:
            self._client.close()

    def _reset(self):
        if self._client is not None:
            self._client.close()
        self._client = None
        self.ok, self.error, self.last_ok = None, "", None
        self.version, self.labels, self.player, self._polls = "", {}, None, 0

    def _get_client(self):
        cfg = self._for
        if cfg is None:
            return None
        if self._client is None:
            self._client = KodiClient(*cfg, parent=self)
        return self._client

    # -- polling -------------------------------------------------------------------

    def refresh(self, *_):
        client = self._get_client()
        if client is None:
            return
        if self.ok is None:
            self.w["connection"].setText(
                f"<span style='color:#9e9e9e'>●</span> {tr('Connecting…')}")
        if not self.version:
            client.call("Application.GetProperties", {"properties": ["version", "name"]},
                        self._on_version, self._on_error)
        if self._polls % LABELS_EVERY == 0:
            client.call("XBMC.GetInfoLabels", {"labels": INFO_LABELS},
                        self._on_labels, self._on_error)
        self._polls += 1
        client.call("Player.GetActivePlayers", None, self._on_players, self._on_error)

    def _answered(self):
        self.ok, self.error, self.last_ok = True, "", time.monotonic()

    def _on_error(self, error):
        self.ok, self.error = False, error
        self.version = ""   # asked again when it answers
        self.render()

    def _on_version(self, result):
        version = (result or {}).get("version") or {}
        if isinstance(version, dict) and "major" in version:
            self.version = f"{version['major']}.{version.get('minor', 0)}"
        self._answered()
        self.render()

    def _on_labels(self, result):
        self.labels = result if isinstance(result, dict) else {}
        self._answered()
        self.render()

    def _on_players(self, result):
        self._answered()
        players = result if isinstance(result, list) else []
        if not players:
            self.player = None
            self.render()
            return
        player_id = players[0].get("playerid")
        kind = players[0].get("type", "")
        client = self._get_client()

        def on_item(item_result):
            item = (item_result or {}).get("item") or {}
            client.call("Player.GetProperties",
                        {"playerid": player_id, "properties": PLAYER_PROPERTIES},
                        lambda props: on_props(item, props), self._on_error)

        def on_props(item, props):
            props = props or {}
            self.player = {"id": player_id, "type": kind, "title": item_title(item),
                           "time": seconds(props.get("time")) or 0,
                           "total": seconds(props.get("totaltime")) or 0,
                           "speed": props.get("speed", 0), "at": time.monotonic()}
            self.render()

        client.call("Player.GetItem", {"playerid": player_id, "properties": ITEM_PROPERTIES},
                    on_item, self._on_error)

    # -- remote --------------------------------------------------------------------

    def play_pause(self, *_):
        self._player_command("Player.PlayPause")

    def stop_playback(self, *_):
        self._player_command("Player.Stop")

    def _player_command(self, method):
        client = self._get_client()
        if client is None or not self.player:
            return
        client.call(method, {"playerid": self.player["id"]},
                    lambda _result: self.refresh(), self._on_error)

    # -- display -------------------------------------------------------------------

    def position(self):
        """Current playback time: the last one read, run on while playing."""
        player = self.player or {}
        elapsed = time.monotonic() - player.get("at", time.monotonic())
        now = player.get("time", 0) + (elapsed * player.get("speed", 0))
        total = player.get("total", 0)
        return min(now, total) if total else now

    def render(self):
        """Also called every second by the panel."""
        if self.ok is None:
            return
        if self.ok:
            text = tr("Connected · updated {seconds} s ago").format(
                seconds=int(time.monotonic() - self.last_ok))
            self.w["connection"].setText(f"<span style='color:#2e7d32'>●</span> {text}")
            self.w["connection"].setToolTip("")
        else:
            self.w["connection"].setText(
                f"<span style='color:#c62828'>●</span> {tr('Unreachable')}")
            self.w["connection"].setToolTip(self.error)
        online = bool(self.ok)
        labels = self.labels if online else {}
        # Line 2: Kodi <version> · <system>
        self.w["name"].setTextFormat(Qt.TextFormat.PlainText)
        self.w["name"].setText(" · ".join(p for p in (
            f"Kodi {self.version}" if self.version else "Kodi",
            labels.get("System.OSVersionInfo", "")) if p))
        # Line 3: IP · uptime · CPU temperature (as Kodi words them)
        host = labels.get("Network.IPAddress") or self._host()
        uptime = labels.get("System.Uptime", "")
        temp = labels.get("System.CPUTemperature", "")
        self.w["info"].setText(" · ".join(p for p in (
            host, tr("up {duration}").format(duration=uptime) if uptime else "",
            tr("CPU {temperature}").format(temperature=temp) if temp else "") if p))
        # Line 4: what is playing
        player = self.player if online else None
        self.w["play_row"].setVisible(online)
        for name in ("progress", "play", "stop"):
            self.w[name].setVisible(player is not None)
        if player is None:
            self.w["playing"].setText(tr("Idle") if online else "")
            return
        paused = player.get("speed", 0) == 0
        now, total = self.position(), player.get("total", 0)
        times = f"{clock(now)} / {clock(total)}" if total else clock(now)
        self.w["playing"].setTextFormat(Qt.TextFormat.PlainText)
        self.w["playing"].setText(f"{'⏸' if paused else '▶'} {player['title']} · {times}")
        self.w["progress"].setValue(int(100 * now / total) if total else 0)
        self.w["play"].setToolTip(tr("Play") if paused else tr("Pause"))
        self.w["play"].setText("▶" if paused else "⏸")

    def _host(self):
        cfg = self._for
        return QUrl(rpc_url(cfg[0])).host() if cfg else ""
