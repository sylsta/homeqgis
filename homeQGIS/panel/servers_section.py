"""The servers in the panel: a frame each in the Status tab, their web
interfaces, remote desktops, SSH and Wake-on-LAN, and the strip's icons."""

import html

from qgis.PyQt.QtCore import QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QLabel, QMenu, QToolButton
from qgis.core import Qgis

from ..core.i18n import tr
from ..core.icons import icon
from ..core.settings import PLUGIN_NAME, active_robot_id, has_secret, load_settings, secret
from ..home.ha_block import HaBlock
from ..servers import system_terminal, remote_desktop, wol, model as servers_model, ssh_auth
from ..servers.editor import TYPE_ICONS as SERVER_ICONS, display_name as server_display_name
from ..servers.frames import PortBlock, ServerFrame, WebBlock
from ..servers.kodi_block import KodiBlock
from ..servers.kodi_client import rpc_url as kodi_rpc_url
from ..servers.ssh_host_block import SshHostBlock

HA_SUPERVISOR_PORT = 4327   # the Supervisor's web interface, on Home Assistant's host
WAKE_CHECK_MS = 30_000      # after a Wake-on-LAN, the server is checked again then (twice)
def _on_port(url, port):
    """url's scheme and host on another port ("" if url has no host)."""
    parts = QUrl(url if "://" in url else "http://" + url) if url else QUrl()
    if not parts.host():
        return ""
    return f"{parts.scheme() or 'http'}://{parts.host()}:{port}/"


class ServersMixin:
    """Part of ValetudoPanel (see status_panel.py)."""

    @staticmethod
    def _servers():
        return load_settings()["servers"]

    def _build_server_frames(self):
        """A frame (and a block keeping it up to date) per server of the settings, in
        their order, the robot's own frame where the robot in use is; a pill in the
        strip for each one shown there; consoles and logs for those with SSH."""
        self._drop_server_frames()
        cfg = load_settings()
        self._strip_dots = cfg["strip_dots"]   # dots or On the air labels
        servers = cfg["servers"]
        robot = servers_model.active_robot(servers, active_robot_id())
        layout = self.robot_header.parentWidget().layout()
        index = layout.indexOf(self.robot_header)
        layout.removeWidget(self.robot_header)
        strip_index = self.strip_layout.indexOf(self.sep_servers) + 1
        robot_placed = False
        for server in servers:
            if server["type"] == "valetudo":
                if not robot_placed and (robot is None or server is robot):
                    layout.insertWidget(index, self.robot_header)
                    index += 1
                    robot_placed = True
                continue
            entry = self._make_server_entry(server, servers)
            layout.insertWidget(index, entry["frame"])
            index += 1
            if server.get("strip", True):
                for widget in entry["strip"]:
                    self.strip_layout.insertWidget(strip_index, widget)
                    strip_index += 1
            self._server_entries.append(entry)
        if not robot_placed:
            layout.insertWidget(index, self.robot_header)
        self._update_server_buttons()
        self._update_strip_servers()
        if self._term_device not in ("robot", *self._term_pages_devices()):
            self._term_device = "robot"
        self._show_terminal_page()

    def _drop_server_frames(self):
        for entry in self._server_entries:
            for action in entry["actions"]:   # their menu goes with the frame
                if action in self._terminal_entries:
                    self._terminal_entries.remove(action)
            entry["block"].stop()
            for view in entry["views"]:
                view.shutdown()
                if view in self.consoles:
                    self.consoles.remove(view)
                if view in self.logs:
                    self.logs.remove(view)
            for page in entry["pages"].values():
                self.terminal_stack.removeWidget(page)
                page.deleteLater()
            self.robot_header.parentWidget().layout().removeWidget(entry["frame"])
            for widget in entry["strip"]:
                self.strip_layout.removeWidget(widget)
            for widget in (entry["frame"], *entry["strip"]):
                widget.setParent(None)
                widget.deleteLater()
            self._set_problem(f"clock_{entry['id']}", None)
        self._server_entries = []

    def _make_server_entry(self, server, servers):
        kind, sid = server["type"], server["id"]
        name = server_display_name(server, servers)
        logo = SERVER_ICONS[kind]
        frame = ServerFrame(name, icon(logo).pixmap(20, 20), kind)
        w = frame.widgets

        def clock(wrong, n=name, i=sid):
            self._set_problem(f"clock_{i}", tr("The clock of {name} is wrong.").format(name=n)
                              if wrong else None, "maintenance")

        def fresh():   # the server as now in the settings (it may have been edited)
            return servers_model.find(self._servers(), sid) or server

        if kind in ("rpi", "linux"):
            block = SshHostBlock(w, lambda: self._ssh_for(fresh()), self._local_time, clock,
                                 self)
        elif kind == "ha":
            block = HaBlock(w, lambda: servers_model.address(self._servers(), fresh()),
                            lambda: secret(servers_model.secret_key(fresh(), "token")).strip(),
                            self._local_time, self)
        elif kind == "kodi":
            block = KodiBlock(w, lambda: self._kodi_login(fresh()), self)
        elif kind == "windows":
            block = PortBlock(w, lambda: self._windows_port(fresh()), self)
        else:
            block = WebBlock(w, lambda: servers_model.address(self._servers(), fresh()), self)
        frame.setVisible(True)
        logo_label, pill = QLabel(), QLabel()
        logo_label.setPixmap(icon(logo).pixmap(16, 16))
        entry = {"id": sid, "server": server, "name": name, "frame": frame, "block": block,
                 "strip": (logo_label, pill), "views": [], "pages": {}, "actions": []}
        frame.btn_web.setIcon(icon("web"))
        frame.btn_web.clicked.connect(lambda _=False: self.open_web(sid))
        if kind == "ha":
            menu = QMenu(frame.btn_web)
            menu.addAction(icon("web"), "Home Assistant", lambda: self.open_web(sid))
            menu.addAction(icon("web"), tr("Supervisor (port {port})").format(
                port=HA_SUPERVISOR_PORT), lambda: self.open_web(sid, supervisor=True))
            frame.btn_web.setMenu(menu)
            frame.btn_web.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        frame.btn_wake.setIcon(icon("wake"))
        frame.btn_wake.clicked.connect(lambda _=False: self.wake(sid))
        frame.btn_rd.setIcon(icon("remote_desktop"))
        frame.btn_rd.clicked.connect(lambda _=False: self.open_remote_desktop(sid))
        frame.btn_ssh.setIcon(icon("tab_terminal"))
        frame.btn_ssh.clicked.connect(lambda _=False: self.open_ssh(sid))
        self._add_terminal_pages(entry, fresh)
        if entry["pages"]:
            menu = QMenu(frame.btn_ssh)
            menu.addAction(icon("tab_terminal"), tr("Terminal window"),
                           lambda: self.open_ssh(sid))
            for mode, label in (("console", tr("Console in QGIS")), ("log", tr("Log in QGIS"))):
                if mode in entry["pages"]:
                    action = menu.addAction(label, lambda m=mode: self.open_terminal(sid, m))
                    advanced = getattr(self, "act_advanced", None)
                    action.setVisible(advanced.isChecked() if advanced is not None
                                      else load_settings()["advanced_tools"])
                    self._terminal_entries.append(action)
                    entry["actions"].append(action)
            frame.btn_ssh.setMenu(menu)
            frame.btn_ssh.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        return entry

    def _ssh_for(self, server):
        """(host, user, port) for SSH on a server, or None; registers its SSH password
        (Home Assistant), if one is stored."""
        target = servers_model.ssh_target(self._servers(), server)
        if target is not None and "ssh_password" in servers_model.secret_fields(server["type"]):
            key = servers_model.secret_key(server, "ssh_password")
            if self._ssh_passwords.get(server["id"]) != target:
                ssh_auth.set_password(*target, secret(key) if has_secret(key) else "")
                self._ssh_passwords[server["id"]] = target
        return target

    def _kodi_login(self, server):
        url = servers_model.address(self._servers(), server)
        if not url:
            return None
        key = servers_model.secret_key(server, "password")
        return (url, servers_model.value(server, "user"), secret(key) if has_secret(key) else "")

    def _windows_port(self, server):
        """(host, port, what) to check a Windows computer: its SSH, else RDP or VNC."""
        host = servers_model.ssh_address(servers_model.value(server, "host"), "", 22)[0]
        if not host:
            return None
        if servers_model.value(server, "ssh"):
            return host, servers_model.value(server, "port"), "SSH"
        protocol = servers_model.value(server, "rd_protocol")
        if protocol == "vnc":
            return host, servers_model.value(server, "vnc_port"), "VNC"
        return host, servers_model.value(server, "rdp_port"), "RDP"

    def _entry(self, sid):
        return next((e for e in self._server_entries if e["id"] == sid), None)

    def _server_web(self, sid, supervisor=False):
        """Address of a server's web interface, or "" ("robot": the robot's)."""
        if sid == "robot":
            url = load_settings()["url"]
        else:
            entry = self._entry(sid)
            server = servers_model.find(self._servers(), sid) if entry else None
            if server is None:
                return ""
            kind = server["type"]
            address = servers_model.address(self._servers(), server)
            if kind == "ha":
                url = _on_port(address, HA_SUPERVISOR_PORT) if supervisor else address
            elif kind == "kodi":
                url = kodi_rpc_url(address)[:-len("jsonrpc")] if address else ""
            elif kind == "web":
                url = address
            else:
                url = servers_model.value(server, "web_url")
        url = (url or "").strip()
        if url and "://" not in url:
            url = "http://" + url
        return url

    def _server_ssh(self, sid):
        if sid == "robot":
            return self._ssh_target()
        server = servers_model.find(self._servers(), sid)
        return self._ssh_for(server) if server is not None else None

    def _remote_desktops(self, sid):
        server = servers_model.find(self._servers(), sid)
        return servers_model.remote_desktops(self._servers(), server) if server else []

    def _update_server_buttons(self):
        """Each button only where there is something to open; the tooltip says what.
        Which are available is kept: _apply_server_state() then shows them according
        to whether the server is up."""
        rows = [("robot", self.btn_robot_web, None, self.btn_robot_ssh)]
        rows += [(e["id"], e["frame"].btn_web, e["frame"].btn_rd, e["frame"].btn_ssh)
                 for e in self._server_entries]
        for sid, web, rd, ssh in rows:
            url, target = self._server_web(sid), self._server_ssh(sid)
            web.setVisible(bool(url))
            tip = tr("Open the web interface in the browser: {url}").format(url=url)
            entry = self._entry(sid)
            if url and entry is not None and entry["server"]["type"] == "ha":
                tip += "\n" + tr("Its arrow: the Supervisor's interface, {url}").format(
                    url=self._server_web(sid, supervisor=True))
            web.setToolTip(tip)
            ssh.setVisible(target is not None)
            if target is not None:
                ssh.setToolTip(tr("Open an SSH session in a terminal: {command}").format(
                    command=system_terminal.describe(*target)))
            if rd is not None:
                self._update_rd_button(sid, rd)
            self._available[sid] = {"web": bool(url), "ssh": target is not None,
                                    "rd": rd is not None and bool(self._remote_desktops(sid))}
        for entry in self._server_entries:
            server = servers_model.find(self._servers(), entry["id"]) or entry["server"]
            target = servers_model.wake_target(self._servers(), server)
            self._available[entry["id"]]["wake"] = target is not None
            if target is not None:
                entry["frame"].btn_wake.setToolTip(
                    tr("Wake it up (Wake-on-LAN): {mac}").format(mac=target[0]))
        self._apply_server_state()

    def _apply_server_state(self):
        """A server that does not answer: no web, remote desktop or SSH button, but
        Wake-on-LAN; one that answers: the opposite. Before the first answer, both."""
        rows = [("robot", self._reachable, self.btn_robot_web, None, self.btn_robot_ssh, None)]
        rows += [(e["id"], e["block"].ok, e["frame"].btn_web, e["frame"].btn_rd,
                  e["frame"].btn_ssh, e["frame"].btn_wake) for e in self._server_entries]
        for sid, ok, web, rd, ssh, wake in rows:
            available = self._available.get(sid, {})
            up, down = ok is not False, ok is not True
            web.setVisible(available.get("web", False) and up)
            ssh.setVisible(available.get("ssh", False) and up)
            if rd is not None:
                rd.setVisible(available.get("rd", False) and up)
            if wake is not None:
                wake.setVisible(available.get("wake", False) and down)

    def _update_rd_button(self, sid, button):
        desktops = self._remote_desktops(sid)
        button.setVisible(bool(desktops))
        if not desktops:
            return
        lines = [tr("Open the remote desktop: {protocol} on {host}:{port}").format(
            protocol=d[0].upper(), host=d[1], port=d[2])
            + (" " + tr("(through SSH)") if d[4] else "") for d in desktops]
        button.setToolTip("\n".join(lines))
        if len(desktops) > 1:
            menu = QMenu(button)
            for index, desktop in enumerate(desktops):
                menu.addAction(icon("remote_desktop"), desktop[0].upper(),
                               lambda i=index: self.open_remote_desktop(sid, i))
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        else:
            button.setMenu(None)

    def open_remote_desktop(self, sid, index=0):
        desktops = self._remote_desktops(sid)
        if not desktops:
            return
        protocol, host, port, user, ssh = desktops[min(index, len(desktops) - 1)]
        template = load_settings()[f"{protocol}_command"] or remote_desktop.detected(protocol)
        self._rd_protocol = protocol
        self.remote_desktop.open(template, host, port, user, ssh)
        if ssh is not None and template:
            self.show_feedback(tr("Opening the SSH tunnel…"))

    def _on_remote_desktop_failed(self, reason):
        protocol = getattr(self, "_rd_protocol", "vnc").upper()
        self.show_feedback({
            "no_program": tr("No {protocol} program found: install Remmina, or set its "
                             "command in the settings (Servers tab).").format(protocol=protocol),
            "tunnel": tr("The SSH tunnel could not be opened (SSH key or password, address?)."),
        }.get(reason, tr("The remote desktop program could not be started.")), "warning")

    def open_web(self, sid, supervisor=False):
        url = self._server_web(sid, supervisor)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def wake(self, sid):
        """Send the Wake-on-LAN packet; the frame says when it answers."""
        entry = self._entry(sid)
        server = servers_model.find(self._servers(), sid)
        target = servers_model.wake_target(self._servers(), server) if server else None
        if entry is None or target is None:
            return
        problem = wol.wake(*target)
        if problem == "bad_mac":
            text, level = tr("{name}: “{mac}” is not a MAC address (settings, Servers)."), \
                Qgis.MessageLevel.Warning
        elif problem:
            text, level = tr("{name}: Wake-on-LAN not sent: {error}"), Qgis.MessageLevel.Warning
        else:
            text, level = tr("{name}: Wake-on-LAN sent to {mac}. It may take a minute to "
                             "answer."), Qgis.MessageLevel.Info
            for delay in (WAKE_CHECK_MS, 2 * WAKE_CHECK_MS):
                QTimer.singleShot(delay, lambda: self._refresh_server(sid))
        from qgis.utils import iface
        if iface is not None:
            iface.messageBar().pushMessage(
                PLUGIN_NAME, text.format(name=entry["name"], mac=target[0], error=problem),
                level=level, duration=6)

    def _refresh_server(self, sid):
        entry = self._entry(sid)   # (the frames may have been rebuilt since)
        if entry is not None:
            entry["block"].refresh()

    def open_ssh(self, sid):
        target = self._server_ssh(sid)
        if target is None:
            return
        problem = system_terminal.open_ssh(*target, tr("Press Enter to close."))
        if problem == "no_terminal":
            self.show_feedback(tr("No terminal program found: set the TERMINAL environment "
                                  "variable to the one you use."), "warning")
        elif problem:
            self.show_feedback(tr("The terminal could not be started."), "warning")

    def _update_servers(self):
        """The servers' blocks read while the panel is visible."""
        for entry in self._server_entries:
            entry["block"].update(self.isVisible())

    def _update_strip_tip(self):
        """What a click on the strip does, then the Wi-Fi signal (no longer shown in it)."""
        lines = [tr("Click to unfold or fold the panel") if self.is_compact()
                 else tr("Click for the detailed status")]
        wifi = getattr(self, "_wifi_html", "")
        if wifi:
            lines.append(wifi + (" · " + html.escape(self._wifi_tip) if self._wifi_tip else ""))
        self.strip.setToolTip("<br>".join(lines))

    def _update_strip_servers(self):
        """The servers in the strip: logo and a pill styled like the robot's state."""
        pills = {"on": ("#2e7d32", tr("On the air")), "off": ("#c62828", tr("Off the air")),
                 "connecting": ("#9e9e9e", tr("Connecting…")),
                 "no_token": ("#ef6c00", tr("No token"))}
        shown = False
        dots = getattr(self, "_strip_dots", False)
        for entry in self._server_entries:
            logo, pill = entry["strip"]
            on_strip = bool(entry["server"].get("strip", True))
            logo.setVisible(on_strip)
            pill.setVisible(on_strip)
            shown |= on_strip
            if not on_strip:
                continue
            block = entry["block"]
            state = block.strip_state()
            color, text = pills.get(state, pills["connecting"])
            if dots:   # just a coloured dot (UI configuration)
                pill.setText("●")
                pill.setStyleSheet(f"color: {color}; font-size: 14px;")
            else:
                pill.setText(text)
                pill.setStyleSheet(f"background-color: {color}; color: white; "
                                   "font-weight: bold; border-radius: 8px; padding: 1px 8px;")
            details = entry["frame"].connection.text()
            extra = block.tooltip() if hasattr(block, "tooltip") else ""
            tip = (f"<b>{html.escape(entry['name'])}</b>: {html.escape(text)}<br>{details}"
                   + (f"<br>{html.escape(extra)}" if extra else ""))
            logo.setToolTip(tip)
            pill.setToolTip(tip)
        self.sep_servers.setVisible(shown)   # one separator before the servers
