"""The plugin's page in QGIS Settings › Options (layout: ``ui/settings_page.ui``).

QGIS calls ``apply()`` when the Options dialog is closed with OK (or Apply);
Cancel saves nothing, like the other Options pages.
"""

import time

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QStackedWidget
from qgis.core import QgsSettings
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory

from . import host_info, room_groups
from .client import ValetudoClient
from .ha_client import UNAUTHORISED, HomeAssistantClient
from .i18n import tr
from .robot_survey import RobotSurvey
from .icons import LOGO, icon
from .settings import (
    DEFAULT_CAMERA_PORT, KEY_AUTH, KEY_CAMERA_URL, KEY_CAMERA_WIDTH, KEY_FFMPEG,
    KEY_HA_LOG_COMMAND, KEY_HA_SSH_HOST, KEY_HA_SSH_PORT, KEY_HA_SSH_USER,
    KEY_HA_URL, KEY_INTERVAL, KEY_LIVE_AT_START, KEY_NOTIFY_DOCK, KEY_PI_HOST,
    KEY_PI_PORT, KEY_PI_USER, KEY_PI_WIFI_DIR, KEY_SSH_PORT, KEY_SSH_USER, KEY_URL,
    HA_SSH_PASSWORD_SETTING, HA_TOKEN_SETTING, WIFI_DEFAULTS, default_camera_url,
    load_settings, secret, set_secret,
)
from .ui_loader import load_ui

PAGE_NAME = "ValetudoOptionsPage"   # object name of the page (root of settings_page.ui)

UI_WIDGETS = (
    "url", "auth", "interval", "live_at_start", "btn_test", "lbl_test", "btn_room_groups",
    "camera_url", "ffmpeg", "camera_width", "notify_dock", "ssh_user", "ssh_port",
    "pi_host", "pi_user", "pi_port", "pi_wifi_dir", "btn_pi_test", "lbl_pi_test",
    "ha_url", "ha_token", "btn_ha_test", "lbl_ha_test",
    "ha_ssh_host", "ha_ssh_user", "ha_ssh_port", "ha_ssh_password", "ha_log_command",
    *WIFI_DEFAULTS,   # one widget per Wi-Fi survey setting, named like the setting
)


class ValetudoOptionsPage(QgsOptionsPageWidget):
    def __init__(self, parent=None, on_applied=None):
        super().__init__(parent)
        load_ui("settings_page.ui", self, UI_WIDGETS)
        self.setObjectName(PAGE_NAME)
        self._on_applied = on_applied
        self._test_client = None
        self._ha_client = None

        s = QgsSettings()
        cfg = load_settings()
        self.url.setText(cfg["url"])
        self.auth.setConfigId(cfg["authcfg"])
        self.interval.setValue(cfg["interval_s"])
        self.live_at_start.setChecked(cfg["live_at_start"])
        # Empty camera URL = derived from the robot address.
        self.camera_url.setText(s.value(KEY_CAMERA_URL, "", type=str))
        self.camera_url.setPlaceholderText(
            default_camera_url(cfg["url"]) or f"tcp://192.168.1.23:{DEFAULT_CAMERA_PORT}")
        self.ffmpeg.setText(cfg["ffmpeg"])
        self.camera_width.setValue(cfg["camera_width"])
        self.notify_dock.setChecked(cfg["notify_dock"])
        self.ssh_user.setText(cfg["ssh_user"])
        self.ssh_port.setValue(cfg["ssh_port"])
        self.pi_host.setText(cfg["pi_host"])
        self.pi_user.setText(cfg["pi_user"])
        self.pi_port.setValue(cfg["pi_port"])
        self.pi_wifi_dir.setText(cfg["pi_wifi_dir"])
        self.ha_url.setText(cfg["ha_url"])
        self.ha_ssh_host.setText(cfg["ha_ssh_host"])
        self.ha_ssh_host.setPlaceholderText(
            QUrl(cfg["ha_url"]).host() or "192.168.50.1")
        self.ha_ssh_user.setText(cfg["ha_ssh_user"])
        self.ha_ssh_port.setValue(cfg["ha_ssh_port"])
        self.ha_log_command.setText(cfg["ha_log_command"])
        # Secrets (encrypted): field -> (storage key, value as last saved)
        self._secrets = {self.ha_token: [HA_TOKEN_SETTING, secret(HA_TOKEN_SETTING).strip()],
                         self.ha_ssh_password: [HA_SSH_PASSWORD_SETTING,
                                                secret(HA_SSH_PASSWORD_SETTING)]}
        for field, (_, value) in self._secrets.items():
            field.setText(value)
        for key, (_, kind) in WIFI_DEFAULTS.items():
            widget = getattr(self, key)
            if kind is bool:
                widget.setChecked(cfg[key])
            else:
                widget.setValue(cfg[key])

        self.btn_test.clicked.connect(self._test_connection)
        self.btn_ha_test.clicked.connect(self._test_home_assistant)
        self.btn_pi_test.clicked.connect(self._test_pi)
        self._pi_runner = None
        self.btn_room_groups.setToolTip(room_groups.file_path())
        self.btn_room_groups.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(room_groups.ensure_file())))

    def _test_connection(self, *_):
        """Ask the robot who it is, with the values being edited (nothing is saved)."""
        url = self.url.text().strip()
        if not url:
            self.lbl_test.setText(tr("Enter the robot address first."))
            return
        self.btn_test.setEnabled(False)
        self.lbl_test.setText(tr("Testing…"))
        self._test_client = ValetudoClient(url, self.auth.configId(), self)

        def ok(info):
            robot = " ".join(p for p in ((info or {}).get("manufacturer"),
                                         (info or {}).get("modelName")) if p) or "Valetudo"
            self.lbl_test.setText("✓ " + tr("Connected: {robot}").format(robot=robot))
            self.btn_test.setEnabled(True)

        def failed(error):
            self.lbl_test.setText("✗ " + tr("Connection failed: {error}").format(error=error))
            self.btn_test.setEnabled(True)

        self._test_client.probe("/robot", ok, failed, timeout_ms=5000)

    def _test_pi(self, *_):
        """Log in over SSH with the values being edited: name, system, maps folder."""
        host = self.pi_host.text().strip()
        if not host:
            self.lbl_pi_test.setText(tr("Enter the server address first."))
            return
        if self._pi_runner is None:
            self._pi_runner = RobotSurvey(self)
            self._pi_runner.finished.connect(self._on_pi_test)
        if self._pi_runner.is_busy():
            return
        self.btn_pi_test.setEnabled(False)
        self.lbl_pi_test.setText(tr("Testing…"))
        self._pi_runner.run("pi_test", host, self.pi_user.text().strip() or "pi",
                            self.pi_port.value(),
                            host_info.pi_test_command(self.pi_wifi_dir.text().strip()))

    def _on_pi_test(self, _operation, ok, output, detail):
        self.btn_pi_test.setEnabled(True)
        if not ok:
            self.lbl_pi_test.setText("✗ " + tr("Connection failed: {error}").format(
                error=detail or tr("no answer")))
            return
        pi = host_info.parse_pi(output, time.time())
        name = " · ".join(p for p in (pi.get("hostname"), pi.get("uname")) if p)
        maps = host_info.parse_maps_line(output)
        folder = self.pi_wifi_dir.text().strip() or "valetudo_wifi"
        if maps is None:
            maps_text = tr("no folder {folder} yet").format(folder=folder)
        else:
            maps_text = tr("{count} Wi-Fi maps in {folder}").format(count=maps, folder=folder)
        self.lbl_pi_test.setText("✓ " + tr("Connected: {name}").format(name=name or host)
                                 + "\n" + maps_text)

    def _test_home_assistant(self, *_):
        """Ask Home Assistant who it is, with the values being edited.

        The token is optional: without one, Home Assistant only says it is
        there (401), which the test reports as found.
        """
        url, token = self.ha_url.text().strip(), self.ha_token.text().strip()
        if not url:
            self.lbl_ha_test.setText(tr("Enter the server address first."))
            return
        if self._ha_client is not None:
            self._ha_client.close()
        self.btn_ha_test.setEnabled(False)
        self.lbl_ha_test.setText(tr("Testing…"))
        self._ha_client = HomeAssistantClient(url, token, self)

        def ok(config):
            config = config if isinstance(config, dict) else {}
            name = config.get("location_name") or "Home Assistant"
            version = config.get("version", "")
            self.lbl_ha_test.setText("✓ " + tr("Connected: {name}").format(
                name=f"{name} ({version})" if version else name))
            self.btn_ha_test.setEnabled(True)

        def failed(error):
            if error == UNAUTHORISED:
                self.lbl_ha_test.setText("✓ " + tr(
                    "Home Assistant found. Without an access token, the plugin "
                    "cannot read or control it."))
            else:
                self.lbl_ha_test.setText(
                    "✗ " + tr("Connection failed: {error}").format(error=error))
            self.btn_ha_test.setEnabled(True)

        self._ha_client.get("/config", ok, failed, timeout_ms=5000)

    def apply(self):
        before = load_settings()
        s = QgsSettings()
        s.setValue(KEY_URL, self.url.text().strip())
        s.setValue(KEY_AUTH, self.auth.configId())
        s.setValue(KEY_INTERVAL, self.interval.value())
        s.setValue(KEY_LIVE_AT_START, self.live_at_start.isChecked())
        s.setValue(KEY_CAMERA_URL, self.camera_url.text().strip())
        s.setValue(KEY_FFMPEG, self.ffmpeg.text().strip())
        s.setValue(KEY_CAMERA_WIDTH, self.camera_width.value())
        s.setValue(KEY_NOTIFY_DOCK, self.notify_dock.isChecked())
        s.setValue(KEY_SSH_USER, self.ssh_user.text().strip() or "root")
        s.setValue(KEY_SSH_PORT, self.ssh_port.value())
        s.setValue(KEY_PI_HOST, self.pi_host.text().strip())
        s.setValue(KEY_PI_USER, self.pi_user.text().strip() or "pi")
        s.setValue(KEY_PI_PORT, self.pi_port.value())
        s.setValue(KEY_PI_WIFI_DIR, self.pi_wifi_dir.text().strip() or "valetudo_wifi")
        s.setValue(KEY_HA_URL, self.ha_url.text().strip())
        s.setValue(KEY_HA_SSH_HOST, self.ha_ssh_host.text().strip())
        s.setValue(KEY_HA_SSH_USER, self.ha_ssh_user.text().strip() or "root")
        s.setValue(KEY_HA_SSH_PORT, self.ha_ssh_port.value())
        s.setValue(KEY_HA_LOG_COMMAND, self.ha_log_command.text().strip())
        secrets_changed = False
        for field, entry in self._secrets.items():
            key, saved = entry
            value = field.text().strip() if field is self.ha_token else field.text()
            if value == saved:
                continue
            if set_secret(key, value):
                entry[1] = value
                secrets_changed = True
            else:
                from qgis.utils import iface
                iface.messageBar().pushWarning("Valetudo", tr(
                    "A Home Assistant token or password was not saved: the QGIS "
                    "master password is needed to store it encrypted."))
        for key, (_, kind) in WIFI_DEFAULTS.items():
            widget = getattr(self, key)
            s.setValue(f"valetudo/{key}", widget.isChecked() if kind is bool else widget.value())
        # OK is pressed for any Options page: only react when ours changed something.
        if self._on_applied is not None and (secrets_changed or load_settings() != before):
            self._on_applied()


class ValetudoOptionsFactory(QgsOptionsWidgetFactory):
    """Registered with iface.registerOptionsWidgetFactory() while the plugin is loaded."""

    def __init__(self, on_applied=None):
        super().__init__(tr("Valetudo"), icon(LOGO))
        self._on_applied = on_applied
        self._page = None

    def icon(self):
        return icon(LOGO)

    def createWidget(self, parent):
        self._page = ValetudoOptionsPage(parent, self._on_applied)
        return self._page

    def select_page(self):
        """Show our page in the open Options dialog.

        Backs up showOptionsDialog(currentPage=…), which matches the object
        name of the stacked pages: QGIS may wrap a plugin page in a scroll area.
        """
        widget = self._page
        try:
            for _ in range(10):   # the dialog's stack is a few levels up at most
                if widget is None:
                    return
                parent = widget.parentWidget()
                if isinstance(parent, QStackedWidget):
                    parent.setCurrentWidget(widget)
                    return
                widget = parent
        except RuntimeError:   # the page of a previous, closed dialog
            pass
