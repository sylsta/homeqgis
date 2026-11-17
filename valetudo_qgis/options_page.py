"""The plugin's page in QGIS Settings › Options (layout: ``ui/settings_page.ui``).

QGIS calls ``apply()`` when the Options dialog is closed with OK (or Apply);
Cancel saves nothing, like the other Options pages.
"""

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QStackedWidget
from qgis.core import QgsSettings
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory

from . import room_groups
from .client import ValetudoClient
from .i18n import tr
from .icons import LOGO, icon
from .settings import (
    DEFAULT_CAMERA_PORT, KEY_AUTH, KEY_CAMERA_URL, KEY_CAMERA_WIDTH, KEY_FFMPEG,
    KEY_INTERVAL, KEY_NOTIFY_DOCK, KEY_PI_HOST, KEY_PI_PORT, KEY_PI_USER, KEY_PI_WIFI_DIR, KEY_SSH_PORT,
    KEY_SSH_USER, KEY_URL, WIFI_DEFAULTS,
    default_camera_url, load_settings,
)
from .ui_loader import load_ui

PAGE_NAME = "ValetudoOptionsPage"   # object name of the page (root of settings_page.ui)

UI_WIDGETS = (
    "url", "auth", "interval", "btn_test", "lbl_test", "btn_room_groups",
    "camera_url", "ffmpeg", "camera_width", "notify_dock", "ssh_user", "ssh_port",
    "pi_host", "pi_user", "pi_port", "pi_wifi_dir",
    *WIFI_DEFAULTS,   # one widget per Wi-Fi survey setting, named like the setting
)


class ValetudoOptionsPage(QgsOptionsPageWidget):
    def __init__(self, parent=None, on_applied=None):
        super().__init__(parent)
        load_ui("settings_page.ui", self, UI_WIDGETS)
        self.setObjectName(PAGE_NAME)
        self._on_applied = on_applied
        self._test_client = None

        s = QgsSettings()
        cfg = load_settings()
        self.url.setText(cfg["url"])
        self.auth.setConfigId(cfg["authcfg"])
        self.interval.setValue(cfg["interval_s"])
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
        for key, (_, kind) in WIFI_DEFAULTS.items():
            widget = getattr(self, key)
            if kind is bool:
                widget.setChecked(cfg[key])
            else:
                widget.setValue(cfg[key])

        self.btn_test.clicked.connect(self._test_connection)
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

    def apply(self):
        before = load_settings()
        s = QgsSettings()
        s.setValue(KEY_URL, self.url.text().strip())
        s.setValue(KEY_AUTH, self.auth.configId())
        s.setValue(KEY_INTERVAL, self.interval.value())
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
        for key, (_, kind) in WIFI_DEFAULTS.items():
            widget = getattr(self, key)
            s.setValue(f"valetudo/{key}", widget.isChecked() if kind is bool else widget.value())
        # OK is pressed for any Options page: only react when ours changed something.
        if self._on_applied is not None and load_settings() != before:
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
