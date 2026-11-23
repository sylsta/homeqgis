"""The Servers tab of the settings: the list of servers (see servers.py) on the
left, the selected one's settings on the right, with a connection test.

Nothing is stored here: the Options page reads servers(), secret_changes() and
active_robot() when it is applied.
"""

import copy
import time

from qgis.PyQt.QtCore import QSize, QUrl, Qt
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox, QToolButton,
    QVBoxLayout, QWidget,
)
from qgis.core import QgsNetworkAccessManager
from qgis.gui import QgsAuthConfigSelect

from . import host_info, remote_desktop, wol
from . import servers as model
from .client import ValetudoClient
from .ha_client import UNAUTHORISED, HomeAssistantClient
from .i18n import tr
from .icons import HA_LOGO, KODI_ICON, LOGO, NUC_ICON, RPI_LOGO, icon
from .kodi_client import KodiClient
from .robot_survey import RobotSurvey
from .settings import secret

TYPE_ICONS = {"valetudo": LOGO, "rpi": RPI_LOGO, "ha": HA_LOGO, "kodi": KODI_ICON,
              "linux": NUC_ICON, "windows": "computer", "web": "web"}
ROLE_ID = Qt.ItemDataRole.UserRole


def type_labels():
    return {"valetudo": tr("Valetudo robot"), "rpi": tr("Raspberry Pi"),
            "ha": "Home Assistant", "kodi": "Kodi", "linux": tr("Linux computer"),
            "windows": tr("Windows computer"), "web": tr("Web service")}


def protocol_labels():
    return {"none": tr("None"), "vnc": "VNC", "rdp": "RDP", "both": tr("VNC and RDP")}


def field_labels(kind):
    labels = {"url": tr("Address"), "authcfg": tr("Authentication (optional)"),
              "ssh_user": tr("SSH user"), "ssh_port": tr("SSH port"), "host": tr("Address"),
              "user": tr("SSH user"), "port": tr("SSH port"),
              "wifi_dir": tr("Wi-Fi maps folder"), "web_url": tr("Web address"),
              "runs_on": tr("Runs on"), "token": tr("Access token"),
              "ssh_host": tr("SSH address"), "ssh_password": tr("SSH password"),
              "log_command": tr("Log command"), "password": tr("Password"),
              "rd_protocol": tr("Remote desktop"), "vnc_port": tr("VNC port"),
              "rdp_port": tr("RDP port"), "rd_user": tr("Remote desktop user"),
              "rd_ssh": "", "ssh": "", "mac": tr("MAC address (Wake-on-LAN)")}
    if kind == "kodi":
        labels["user"] = tr("Username")
    return labels


def placeholders(kind, server, servers):
    host = model.url_host(model.address(servers, server))
    return {
        "valetudo": {"url": "http://192.168.1.23", "ssh_user": "root"},
        "rpi": {"host": "192.168.50.1", "user": "pi", "wifi_dir": "valetudo_wifi",
                "web_url": "http://192.168.50.1:3001"},
        "linux": {"host": "192.168.50.2", "user": "root",
                  "log_command": tr("automatic: journalctl, else /var/log/syslog"),
                  "web_url": "https://192.168.50.2:9090"},
        "ha": {"url": "http://192.168.50.2:8123/",
               "token": tr("Optional: long-lived access token"),
               "ssh_host": tr("Home Assistant's host ({host})").format(host=host) if host
               else "192.168.50.2",
               "ssh_user": "root", "ssh_password": tr("Optional: else your SSH key"),
               "log_command": model.DEFAULT_HA_LOG_COMMAND},
        "kodi": {"url": "http://192.168.50.2:8080/", "user": "kodi"},
        "windows": {"host": "192.168.50.3", "web_url": ""},
        "web": {"url": "http://192.168.50.1:3001"},
    }[kind]


def hints(kind):
    return {
        "valetudo": tr("Used only by “Reboot robot (SSH)…”, with your SSH key (no password "
                       "is stored)."),
        "rpi": tr("Optional: a Raspberry Pi or other Linux machine on your network, reached "
                  "with your SSH key. With an address, the panel shows a console for it, and "
                  "“Load latest Wi-Fi map from the Pi” reads the maps folder (relative to "
                  "the user's home, as written by pi/valetudo_wifi_collect.py)."),
        "linux": tr("The Status tab shows its name and system, its clock and uptime, its "
                    "load, memory, disk and temperature, read over SSH every 30 s while the "
                    "panel is visible, and the Terminal tab gets a console and a log on it. "
                    "Login is by SSH key. Log command: empty follows the system journal "
                    "(journalctl) where systemd runs, else /var/log/syslog; reading them "
                    "may need root or the adm group."),
        "ha": tr("Optional: your Home Assistant server. The token is optional too, but "
                 "without it the plugin can only check that Home Assistant is there. Create "
                 "it in Home Assistant, on your profile page (Security › Long-lived access "
                 "tokens). It is kept encrypted in the QGIS authentication database, which "
                 "may ask for your master password.") + "\n\n" + tr(
            "SSH: on Home Assistant OS, install the Terminal & SSH add-on and set its SSH "
            "port in the add-on's Network settings, then either paste your public key "
            "(~/.ssh/id_ed25519.pub) in its authorized_keys option, or set a password here "
            "(kept encrypted). Without an SSH address, Home Assistant's own host is used."),
        "kodi": tr("Optional: with an address, the Status tab shows Kodi: its version, uptime "
                   "and CPU temperature, what is playing, with Play/Pause and Stop. In Kodi: "
                   "Settings › Services › Control, turn on Allow remote control via HTTP and "
                   "set a username and password (port 8080 by default). The password is kept "
                   "encrypted in the QGIS authentication database."),
        "windows": tr("A Windows computer: its remote desktop (RDP, built into Windows: "
                      "Settings › System › Remote Desktop) or a VNC server, and SSH if "
                      "its OpenSSH server is on."),
        "web": tr("Any web interface (Uptime Kuma, Mosquitto's, a router…): the panel shows "
                  "whether it answers, and its web button opens it in the browser."),
    }[kind]


def display_name(server, servers):
    name = (server.get("name") or "").strip()
    if name:
        return name
    where = model.url_host(model.address(servers, server)) or model.value(server, "host") or ""
    return type_labels()[server["type"]] + (f" ({where})" if where else "")


class ServersEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._servers = []
        self._secrets = {}    # server id -> {field: [stored key, saved value, value]}
        self._removed_keys = []
        self._active = ""
        self._form_for = None
        self._runner = None
        self._client = None
        self._build()

    # -- widgets ------------------------------------------------------------------------

    def _build(self):
        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(230)
        self.list.setIconSize(QSize(20, 20))
        self.list.currentRowChanged.connect(lambda *_: self._show_form())
        left.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.btn_add = QToolButton()
        self.btn_add.setText(tr("Add"))
        self.btn_add.setToolTip(tr("Add a server"))
        self.btn_add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_add)
        for kind in model.TYPES:
            menu.addAction(icon(TYPE_ICONS[kind]), type_labels()[kind],
                           lambda k=kind: self.add(k))
        self.btn_add.setMenu(menu)
        self.btn_duplicate = self._tool("⧉", tr("Duplicate the selected server"), self.duplicate)
        self.btn_remove = self._tool("－", tr("Remove the selected server"), self.remove)
        self.btn_up = self._tool("▲", tr("Move up (order of the panel)"), lambda: self.move(-1))
        self.btn_down = self._tool("▼", tr("Move down"), lambda: self.move(1))
        for button in (self.btn_add, self.btn_duplicate, self.btn_remove, self.btn_up,
                       self.btn_down):
            buttons.addWidget(button)
        buttons.addStretch(1)
        left.addLayout(buttons)
        layout.addLayout(left)

        right = QVBoxLayout()
        self.lbl_active = QLabel(tr("Robot in use"))
        self.cmb_active = QComboBox()
        self.cmb_active.currentIndexChanged.connect(self._on_active_changed)
        active_row = QHBoxLayout()
        active_row.addWidget(self.lbl_active)
        active_row.addWidget(self.cmb_active, 1)
        right.addLayout(active_row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        right.addWidget(self.scroll, 1)
        test = QHBoxLayout()
        self.btn_test = QPushButton(tr("Test connection"))
        self.btn_test.clicked.connect(self.test)
        self.lbl_test = QLabel()
        self.lbl_test.setWordWrap(True)
        test.addWidget(self.btn_test)
        test.addWidget(self.lbl_test, 1)
        right.addLayout(test)
        self.lbl_empty = QLabel(tr("No server yet: add one with Add (a Valetudo robot first)."))
        self.lbl_empty.setWordWrap(True)
        right.addWidget(self.lbl_empty)
        tools = QFormLayout()
        tools.addRow(QLabel("<b>" + tr("Remote desktop programs") + "</b>"))
        self.vnc_command, self.rdp_command = QLineEdit(), QLineEdit()
        for protocol, field in (("vnc", self.vnc_command), ("rdp", self.rdp_command)):
            found = remote_desktop.detected(protocol)
            field.setPlaceholderText(found or tr("none found: enter its command"))
            field.setToolTip(tr("Empty: the program found ({found}). A command of your own "
                                "can use {{host}}, {{port}}, {{user}} and {{userat}} "
                                "(the user and @, or nothing).").format(
                                    found=found or tr("none")))
            tools.addRow(tr("{protocol} program").format(protocol=protocol.upper()), field)
        right.addLayout(tools)
        layout.addLayout(right, 1)

    def _tool(self, text, tip, slot):
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    # -- content ------------------------------------------------------------------------

    def load(self, servers, active_id=""):
        self._servers = copy.deepcopy(servers)
        self._secrets, self._removed_keys = {}, []
        self._active = active_id
        self._refresh_list(0 if servers else -1)

    def servers(self):
        return copy.deepcopy(self._servers)

    def load_programs(self, vnc, rdp):
        self.vnc_command.setText(vnc)
        self.rdp_command.setText(rdp)

    def programs(self):
        return self.vnc_command.text().strip(), self.rdp_command.text().strip()

    def active_robot(self):
        robot = model.active_robot(self._servers, self._active)
        return robot["id"] if robot else ""

    def secret_changes(self):
        """[(key, value)] to store ("" removes), for edited and removed servers."""
        changes = [(key, "") for key in self._removed_keys]
        for fields in self._secrets.values():
            for key, saved, current in fields.values():
                if current != saved:
                    changes.append((key, current))
        return changes

    def secrets_saved(self):
        """After storing: the values on screen are now the saved ones."""
        for fields in self._secrets.values():
            for entry in fields.values():
                entry[1] = entry[2]
        self._removed_keys = []

    def _current(self):
        item = self.list.currentItem()
        return model.find(self._servers, item.data(ROLE_ID)) if item else None

    def _refresh_list(self, row=None):
        row = self.list.currentRow() if row is None else row
        self.list.blockSignals(True)
        self.list.clear()
        for server in self._servers:
            item = QListWidgetItem(icon(TYPE_ICONS[server["type"]]),
                                   display_name(server, self._servers))
            item.setData(ROLE_ID, server["id"])
            item.setToolTip(type_labels()[server["type"]])
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self._servers:
            self.list.setCurrentRow(max(0, min(row, len(self._servers) - 1)))
        self._refresh_active()
        self._show_form()

    def _refresh_active(self):
        robots = [s for s in self._servers if s["type"] == "valetudo"]
        self.cmb_active.blockSignals(True)
        self.cmb_active.clear()
        for robot in robots:
            self.cmb_active.addItem(display_name(robot, self._servers), robot["id"])
        current = self.active_robot()
        self.cmb_active.setCurrentIndex(max(0, self.cmb_active.findData(current)))
        self.cmb_active.blockSignals(False)
        for widget in (self.lbl_active, self.cmb_active):
            widget.setVisible(len(robots) > 1)

    def _on_active_changed(self, index):
        self._active = self.cmb_active.itemData(index) or ""

    # -- list actions -------------------------------------------------------------------

    def add(self, kind):
        name = "" if kind == "valetudo" else type_labels()[kind]
        server = model.new_server(kind, name)
        self._servers.append(server)
        self._refresh_list(len(self._servers) - 1)

    def duplicate(self):
        server = self._current()
        if server is None:
            return
        self._load_secrets(server)
        clone = copy.deepcopy(server)
        clone["id"] = model.new_id()
        clone.pop("secret_keys", None)
        clone["name"] = tr("{name} (copy)").format(name=display_name(server, self._servers))
        self._servers.insert(self._servers.index(server) + 1, clone)
        self._secrets[clone["id"]] = {
            field: [model.secret_key(clone, field), "", entry[2]]
            for field, entry in self._secrets.get(server["id"], {}).items()}
        self._refresh_list(self._servers.index(clone))

    def remove(self):
        server = self._current()
        if server is None:
            return
        answer = QMessageBox.question(
            self, tr("Remove a server"),
            tr("Remove {name} from the servers?").format(name=display_name(server, self._servers)))
        if answer != QMessageBox.StandardButton.Yes:
            return
        row = self._servers.index(server)
        self._servers.remove(server)
        self._removed_keys += [model.secret_key(server, f)
                               for f in model.secret_fields(server["type"])]
        self._secrets.pop(server["id"], None)
        for other in self._servers:
            if other.get("runs_on") == server["id"]:
                other["runs_on"] = ""
        self._refresh_list(row)

    def move(self, step):
        server = self._current()
        if server is None:
            return
        row = self._servers.index(server)
        target = row + step
        if 0 <= target < len(self._servers):
            self._servers[row], self._servers[target] = self._servers[target], server
            self._refresh_list(target)

    # -- the selected server's form -----------------------------------------------------

    def _load_secrets(self, server):
        """Read the server's tokens and passwords once (may ask for the master
        password)."""
        if server["id"] in self._secrets:
            return
        fields = {}
        for field in model.secret_fields(server["type"]):
            key = model.secret_key(server, field)
            value = secret(key)
            fields[field] = [key, value, value]
        self._secrets[server["id"]] = fields

    def _show_form(self):
        server = self._current()
        has = server is not None
        for widget in (self.scroll, self.btn_test, self.lbl_test):
            widget.setVisible(has)
        self.lbl_empty.setVisible(not has)
        for button in (self.btn_duplicate, self.btn_remove, self.btn_up, self.btn_down):
            button.setEnabled(has)
        if server is None:
            self._form_for = None
            return
        if self._form_for == server["id"]:
            return
        self._form_for = server["id"]
        self.lbl_test.setText("")
        self._load_secrets(server)
        kind = server["type"]
        page = QWidget()
        form = QFormLayout(page)
        title = QLabel(f"<b>{type_labels()[kind]}</b>")
        form.addRow(title)
        name = QLineEdit(server.get("name", ""))
        name.setPlaceholderText(display_name({**server, "name": ""}, self._servers))
        name.textChanged.connect(lambda text: self._set(server, "name", text))
        form.addRow(tr("Name"), name)
        strip = QCheckBox(tr("Show in the status strip"))
        strip.setChecked(bool(server.get("strip", True)))
        strip.toggled.connect(lambda on: self._set(server, "strip", on, relist=False))
        form.addRow("", strip)
        labels = field_labels(kind)
        examples = placeholders(kind, server, self._servers)
        for field, field_kind, default in model.TYPE_FIELDS[kind]:
            if field == "rd_protocol":
                form.addRow(QLabel("<b>" + tr("Remote desktop") + "</b>"))
            form.addRow(labels[field], self._field(server, field, field_kind, default,
                                                   examples.get(field, "")))
        hint = QLabel(hints(kind))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        form.addRow(hint)
        self.scroll.setWidget(page)

    def _field(self, server, field, kind, default, example):
        if kind == "port":
            widget = QSpinBox()
            widget.setRange(1, 65535)
            widget.setValue(model.value(server, field))
            widget.valueChanged.connect(lambda v: self._set(server, field, v, relist=False))
            return widget
        if kind == "bool":
            texts = {"rd_ssh": tr("Through SSH (an encrypted tunnel: nothing to open on "
                                  "its firewall)"),
                     "ssh": tr("OpenSSH server (SSH button, consoles, tunnel)")}
            widget = QCheckBox(texts.get(field, field))
            widget.setChecked(model.value(server, field))
            widget.toggled.connect(lambda on: self._set(server, field, on, relist=False))
            return widget
        if kind == "choice":
            widget = QComboBox()
            for key, label in protocol_labels().items():
                widget.addItem(label, key)
            widget.setCurrentIndex(max(0, widget.findData(model.value(server, field))))
            widget.currentIndexChanged.connect(
                lambda i, w=widget: self._set(server, field, w.itemData(i), relist=False))
            return widget
        if kind == "authcfg":
            widget = QgsAuthConfigSelect(self)
            widget.setConfigId(server.get(field, ""))
            widget.selectedConfigIdChanged.connect(
                lambda cid: self._set(server, field, cid, relist=False))
            return widget
        if kind == "server":
            widget = QComboBox()
            widget.addItem(tr("(its own address)"), "")
            for other in self._servers:
                if other["type"] in model.HOST_TYPES and other is not server:
                    widget.addItem(icon(TYPE_ICONS[other["type"]]),
                                   display_name(other, self._servers), other["id"])
            widget.setCurrentIndex(max(0, widget.findData(server.get(field, ""))))
            widget.setToolTip(tr("It runs on this computer: its address takes the "
                                 "computer's, with its own port, and SSH goes there."))
            widget.currentIndexChanged.connect(
                lambda i, w=widget: self._set(server, field, w.itemData(i) or ""))
            return widget
        widget = QLineEdit()
        if kind == "secret":
            widget.setEchoMode(QLineEdit.EchoMode.Password)
            entry = self._secrets[server["id"]][field]
            widget.setText(entry[2])

            def changed(text, e=entry):
                e[2] = text.strip() if field == "token" else text
            widget.textChanged.connect(changed)
        else:
            text = str(server.get(field) or "")
            if text == str(default) and str(default) == str(example):
                text = ""   # the default: shown as the placeholder
            widget.setText(text)
            widget.textChanged.connect(lambda text: self._set(server, field, text.strip()))
        if example:
            widget.setPlaceholderText(str(example))
        if field == "mac":
            widget.setPlaceholderText(tr("Optional: aa:bb:cc:dd:ee:ff"))
            tip = tr("The MAC address of its network card: the panel then shows a Wake-on-LAN "
                     "button. Wake-on-LAN must be allowed in its BIOS/UEFI and on its network "
                     "card, usually on a wired connection.")
            if kind == "text" and server["type"] not in model.HOST_TYPES:
                tip += "\n" + tr("When it runs on a computer of the list, that computer's "
                                  "MAC address is used if this one is empty.")
            widget.setToolTip(tip)

            def check(text, w=widget):
                w.setStyleSheet("" if not text.strip() or wol.parse_mac(text)
                                else "color: #c62828;")
            widget.textChanged.connect(check)
            check(widget.text())
        return widget

    def _set(self, server, field, value, relist=True):
        server[field] = value
        if relist:
            item = self.list.currentItem()
            if item is not None:
                item.setText(display_name(server, self._servers))
            self._refresh_active()

    # -- test ---------------------------------------------------------------------------

    def _result(self, ok, text):
        self.lbl_test.setText(("✓ " if ok else "✗ ") + text)
        self.btn_test.setEnabled(True)

    def test(self):
        """Ask the selected server who it is, with the values being edited."""
        server = self._current()
        if server is None:
            return
        kind = server["type"]
        address = model.address(self._servers, server)
        if not address:
            self.lbl_test.setText(tr("Enter the server address first."))
            return
        self.btn_test.setEnabled(False)
        self.lbl_test.setText(tr("Testing…"))
        if kind in ("rpi", "linux"):
            self._test_ssh(server)
        elif kind == "valetudo":
            self._client = ValetudoClient(address, server.get("authcfg", ""), self)

            def ok(info):
                robot = " ".join(p for p in ((info or {}).get("manufacturer"),
                                             (info or {}).get("modelName")) if p) or "Valetudo"
                self._result(True, tr("Connected: {robot}").format(robot=robot))
            self._client.probe("/robot", ok, self._failed, timeout_ms=5000)
        elif kind == "ha":
            token = self._secrets[server["id"]]["token"][2]
            self._client = HomeAssistantClient(address, token, self)

            def ok(config):
                config = config if isinstance(config, dict) else {}
                name = config.get("location_name") or "Home Assistant"
                version = config.get("version", "")
                self._result(True, tr("Connected: {name}").format(
                    name=f"{name} ({version})" if version else name))

            def failed(error):
                if error == UNAUTHORISED:
                    self._result(True, tr("Home Assistant found. Without an access token, "
                                          "the plugin cannot read or control it."))
                else:
                    self._failed(error)
            self._client.get("/config", ok, failed, timeout_ms=5000)
        elif kind == "kodi":
            password = self._secrets[server["id"]]["password"][2]
            self._client = KodiClient(address, model.value(server, "user"), password, self)

            def ok(result):
                version = (result or {}).get("version") or {}
                number = (f" {version['major']}.{version.get('minor', 0)}"
                          if isinstance(version, dict) and "major" in version else "")
                self._result(True, tr("Connected: {name}").format(
                    name=f"{(result or {}).get('name') or 'Kodi'}{number}"))
            self._client.call("Application.GetProperties",
                              {"properties": ["version", "name"]}, ok, self._failed)
        else:
            self._test_web(address)

    def _failed(self, error):
        self._result(False, tr("Connection failed: {error}").format(error=error))

    def _test_ssh(self, server):
        if self._runner is None:
            self._runner = RobotSurvey(self)
            self._runner.finished.connect(self._on_ssh_test)
        if self._runner.is_busy():
            return
        host, user, port = model.ssh_target(self._servers, server)
        command = (host_info.pi_test_command(model.value(server, "wifi_dir"))
                   if server["type"] == "rpi" else host_info.SERVER_COMMAND)
        self._ssh_server = server
        self._runner.run("server_test", host, user, port, command)

    def _on_ssh_test(self, _operation, ok, output, detail):
        server = getattr(self, "_ssh_server", None)
        if not ok:
            self._failed(detail or tr("no answer"))
            return
        info = host_info.parse_pi(output, time.time())
        name = " · ".join(p for p in (info.get("hostname"), info.get("uname")) if p)
        text = tr("Connected: {name}").format(name=name or model.value(server, "host"))
        if server is not None and server["type"] == "rpi":
            maps = host_info.parse_maps_line(output)
            folder = model.value(server, "wifi_dir")
            text += "\n" + (tr("no folder {folder} yet").format(folder=folder) if maps is None
                            else tr("{count} Wi-Fi maps in {folder}").format(count=maps,
                                                                            folder=folder))
        else:
            resources = host_info.resources_line(host_info.parse_resources(output))
            text += ("\n" + resources) if resources else ""
        self._result(True, text)

    def _test_web(self, address):
        url = address if "://" in address else "http://" + address
        reply = QgsNetworkAccessManager.instance().get(QNetworkRequest(QUrl(url)))

        def done():
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if reply.error() == QNetworkReply.NetworkError.NoError or status:
                self._result(True, tr("It answers (HTTP {status}).").format(status=status or "?"))
            else:
                self._failed(reply.errorString())
            reply.deleteLater()
        reply.finished.connect(done)
