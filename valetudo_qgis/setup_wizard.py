"""First-start setup: the robot's address (with a test), then the other servers, in
three short pages. Everything can be changed later in Settings › Options.

    1. Robot      address [http://192.168.50.20]  [Test]  ✓ Connected: Eureka J15…
    2. Servers    ☐ Raspberry Pi    address  user
                  ☐ NUC             address  user
                  ☐ Home Assistant  address
                  ☐ Kodi            address
    3. Done       what was set; where to change it
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                                 QLineEdit, QPushButton, QVBoxLayout, QWizard, QWizardPage)
from qgis.core import QgsSettings

from .client import ValetudoClient
from .i18n import tr
from .icons import APP_ICON, HA_LOGO, KODI_ICON, NUC_ICON, RPI_LOGO, icon
from .settings import (KEY_HA_URL, KEY_KODI_URL, KEY_NUC_HOST, KEY_NUC_USER, KEY_PI_HOST,
                       KEY_PI_USER, KEY_URL, PLUGIN_NAME, load_settings)


def _normalised(url):
    url = url.strip().rstrip("/")
    return url if not url or "://" in url else "http://" + url


class RobotPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle(tr("Your robot"))
        self.setSubTitle(tr("The address of Valetudo on your robot, as you open it in a "
                            "browser."))
        layout = QFormLayout(self)
        self.url = QLineEdit(load_settings()["url"])
        self.url.setPlaceholderText("http://192.168.50.20")
        self.url.textChanged.connect(self.completeChanged)
        layout.addRow(tr("Robot address"), self.url)
        row = QHBoxLayout()
        self.test = QPushButton(tr("Test connection"))
        self.test.clicked.connect(self._test)
        self.result = QLabel()
        self.result.setWordWrap(True)
        row.addWidget(self.test)
        row.addWidget(self.result, 1)
        layout.addRow(row)
        self._client = None

    def isComplete(self):
        return bool(self.url.text().strip())

    def address(self):
        return _normalised(self.url.text())

    def _test(self):
        self.test.setEnabled(False)
        self.result.setText(tr("Testing…"))
        self._client = ValetudoClient(self.address(), "", self)

        def ok(info):
            robot = " ".join(p for p in ((info or {}).get("manufacturer"),
                                         (info or {}).get("modelName")) if p) or "Valetudo"
            self.result.setText("✓ " + tr("Connected: {robot}").format(robot=robot))
            self.test.setEnabled(True)

        def failed(error):
            self.result.setText("✗ " + tr("Connection failed: {error}").format(error=error))
            self.test.setEnabled(True)

        self._client.probe("/robot", ok, failed, timeout_ms=5000)


class ServersPage(QWizardPage):
    """Optional servers: tick the ones you have, give their address."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle(tr("Other servers (optional)"))
        self.setSubTitle(tr("Tick those you have. Their logins (SSH keys, Home Assistant "
                            "token, Kodi password) are set later in the settings."))
        cfg = load_settings()
        grid = QGridLayout()
        self.rows = {}
        specs = [
            ("pi", RPI_LOGO, tr("Raspberry Pi"), cfg["pi_host"], "192.168.50.1", cfg["pi_user"]),
            ("nuc", NUC_ICON, "NUC", cfg["nuc_host"], "192.168.50.2", cfg["nuc_user"]),
            ("ha", HA_LOGO, "Home Assistant", cfg["ha_url"] if self._ha_set() else "",
             "http://192.168.50.2:8123", None),
            ("kodi", KODI_ICON, "Kodi", cfg["kodi_url"], "http://192.168.50.2:8080", None),
        ]
        for row, (key, logo, name, value, example, user) in enumerate(specs):
            box = QCheckBox(name)
            box.setIcon(icon(logo))
            address = QLineEdit(value)
            address.setPlaceholderText(example)
            login = None
            if user is not None:
                login = QLineEdit(user)
                login.setPlaceholderText(tr("SSH user"))
                login.setMaximumWidth(110)
            box.setChecked(bool(value))
            for widget in (address, login):
                if widget is not None:
                    widget.setEnabled(box.isChecked())
                    box.toggled.connect(widget.setEnabled)
            grid.addWidget(box, row, 0)
            grid.addWidget(address, row, 1)
            if login is not None:
                grid.addWidget(login, row, 2)
            self.rows[key] = (box, address, login)
        grid.setColumnStretch(1, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addStretch(1)

    @staticmethod
    def _ha_set():
        """Home Assistant has a default address: only show one the user set."""
        return bool(QgsSettings().value(KEY_HA_URL, "", type=str))

    def values(self):
        """{key: (address, user)} of the ticked servers with an address."""
        out = {}
        for key, (box, address, login) in self.rows.items():
            text = address.text().strip()
            if box.isChecked() and text:
                out[key] = (text, login.text().strip() if login is not None else "")
        return out


class DonePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle(tr("Ready"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addStretch(1)

    def show_summary(self, robot, servers):
        names = {"pi": tr("Raspberry Pi"), "nuc": "NUC", "ha": "Home Assistant", "kodi": "Kodi"}
        lines = [f"<b>{tr('Robot')}</b>: {robot}"]
        lines += [f"<b>{names[key]}</b>: {address}" for key, (address, _) in servers.items()]
        self.summary.setText(
            "<br>".join(lines) + "<br><br>" + tr(
                "Finish saves these, and the panel shows the robot. Everything can be "
                "changed later in Settings › Options › {name}.").format(name=PLUGIN_NAME))


class SetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("{name} setup").format(name=PLUGIN_NAME))
        self.setWindowIcon(icon(APP_ICON))
        self.setPixmap(QWizard.WizardPixmap.LogoPixmap, icon(APP_ICON).pixmap(48, 48))
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.robot = RobotPage(self)
        self.servers = ServersPage(self)
        self.done_page = DonePage(self)
        for page in (self.robot, self.servers, self.done_page):
            self.addPage(page)
        self.currentIdChanged.connect(self._on_page)
        self.resize(620, 420)

    def _on_page(self, _page_id):
        if self.currentPage() is self.done_page:
            self.done_page.show_summary(self.robot.address(), self.servers.values())

    def save(self):
        """Write what was entered (only the fields this wizard asks)."""
        s = QgsSettings()
        s.setValue(KEY_URL, self.robot.address())
        servers = self.servers.values()
        if "pi" in servers:
            s.setValue(KEY_PI_HOST, servers["pi"][0])
            if servers["pi"][1]:
                s.setValue(KEY_PI_USER, servers["pi"][1])
        if "nuc" in servers:
            s.setValue(KEY_NUC_HOST, servers["nuc"][0])
            if servers["nuc"][1]:
                s.setValue(KEY_NUC_USER, servers["nuc"][1])
        if "ha" in servers:
            s.setValue(KEY_HA_URL, _normalised(servers["ha"][0]) + "/")
        if "kodi" in servers:
            s.setValue(KEY_KODI_URL, _normalised(servers["kodi"][0]) + "/")
