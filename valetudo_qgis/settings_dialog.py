"""Settings dialog, stored in QgsSettings.

Passwords are never stored in clear text: credentials go through the QGIS
authentication manager (QgsAuthConfigSelect), which encrypts them.
"""

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)
from qgis.core import QgsSettings
from qgis.gui import QgsAuthConfigSelect

from .client import ValetudoClient
from .i18n import tr

KEY_URL = "valetudo/url"
KEY_AUTH = "valetudo/authcfg"
KEY_INTERVAL = "valetudo/interval_s"
KEY_CAMERA_URL = "valetudo/camera_url"
KEY_FFMPEG = "valetudo/ffmpeg"
KEY_CAMERA_WIDTH = "valetudo/camera_width"
KEY_NOTIFY_DOCK = "valetudo/notify_dock"
KEY_SSH_USER = "valetudo/ssh_user"
KEY_SSH_PORT = "valetudo/ssh_port"

# Wi-Fi survey: setting key -> (default value, type). Read by load_settings().
WIFI_DEFAULTS = {
    "wifi_interval_s": (2.0, float),      # time between two readings
    "wifi_min_step_cm": (20, int),        # ignore a reading closer than this to the last one
    "wifi_max_pos_age_s": (3.0, float),   # ignore a reading if the position is older
    "wifi_pixel_cm": (10, int),           # raster cell size
    "wifi_idw_power": (2.0, float),       # IDW distance coefficient
    "wifi_bad_dbm": (-80, int),           # red
    "wifi_fair_dbm": (-67, int),          # yellow
    "wifi_good_dbm": (-50, int),          # green
    "wifi_opacity": (70, int),            # raster opacity, in %
    "wifi_clip_rooms": (True, bool),      # clip the raster to the rooms
}

DEFAULT_CAMERA_PORT = 8555


def default_camera_url(robot_url):
    """tcp://<robot host>:8555, derived from the robot address."""
    host = QUrl(robot_url).host() if robot_url else ""
    return f"tcp://{host}:{DEFAULT_CAMERA_PORT}" if host else ""


def load_settings():
    s = QgsSettings()
    url = s.value(KEY_URL, "", type=str)
    return {
        "url": url,
        "authcfg": s.value(KEY_AUTH, "", type=str),
        "interval_s": s.value(KEY_INTERVAL, 2, type=int),
        "camera_url": s.value(KEY_CAMERA_URL, "", type=str) or default_camera_url(url),
        "ffmpeg": s.value(KEY_FFMPEG, "", type=str),
        "camera_width": s.value(KEY_CAMERA_WIDTH, 640, type=int),
        "notify_dock": s.value(KEY_NOTIFY_DOCK, True, type=bool),
        "ssh_user": s.value(KEY_SSH_USER, "root", type=str) or "root",
        "ssh_port": s.value(KEY_SSH_PORT, 22, type=int),
        **{key: s.value(f"valetudo/{key}", default, type=kind)
           for key, (default, kind) in WIFI_DEFAULTS.items()},
    }


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Valetudo – settings"))
        s = QgsSettings()
        cfg = load_settings()

        self.url = QLineEdit(cfg["url"])
        self.url.setPlaceholderText("http://192.168.1.23")

        self.auth = QgsAuthConfigSelect(self)
        self.auth.setConfigId(cfg["authcfg"])

        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setSuffix(" s")
        self.interval.setValue(cfg["interval_s"])

        # Empty camera URL = derived from the robot address.
        self.camera_url = QLineEdit(s.value(KEY_CAMERA_URL, "", type=str))
        self.camera_url.setPlaceholderText(
            default_camera_url(cfg["url"]) or f"tcp://192.168.1.23:{DEFAULT_CAMERA_PORT}")

        self.ffmpeg = QLineEdit(cfg["ffmpeg"])
        self.ffmpeg.setPlaceholderText(tr("ffmpeg (found in PATH)"))

        self.camera_width = QSpinBox()
        self.camera_width.setRange(160, 1920)
        self.camera_width.setSingleStep(160)
        self.camera_width.setSuffix(" px")
        self.camera_width.setValue(cfg["camera_width"])

        self.notify_dock = QCheckBox(tr("Warn when a dock tank is empty, full or missing"))
        self.notify_dock.setChecked(cfg["notify_dock"])

        # SSH (robot reboot): key-based login only, no password is ever stored.
        self.ssh_user = QLineEdit(cfg["ssh_user"])
        self.ssh_user.setPlaceholderText("root")
        self.ssh_port = QSpinBox()
        self.ssh_port.setRange(1, 65535)
        self.ssh_port.setValue(cfg["ssh_port"])

        # Wi-Fi survey: one widget per WIFI_DEFAULTS key.
        def spin(key, low, high, suffix, step=1, decimals=None):
            box = QDoubleSpinBox() if decimals is not None else QSpinBox()
            if decimals is not None:
                box.setDecimals(decimals)
            box.setRange(low, high)
            box.setSingleStep(step)
            box.setSuffix(suffix)
            box.setValue(cfg[key])
            return box

        self.wifi = {
            "wifi_interval_s": spin("wifi_interval_s", 0.5, 60, " s", 0.5, 1),
            "wifi_min_step_cm": spin("wifi_min_step_cm", 0, 500, " cm", 5),
            "wifi_max_pos_age_s": spin("wifi_max_pos_age_s", 0.5, 60, " s", 0.5, 1),
            "wifi_pixel_cm": spin("wifi_pixel_cm", 1, 100, " cm"),
            "wifi_idw_power": spin("wifi_idw_power", 0.5, 10, "", 0.5, 1),
            "wifi_bad_dbm": spin("wifi_bad_dbm", -100, 0, " dBm"),
            "wifi_fair_dbm": spin("wifi_fair_dbm", -100, 0, " dBm"),
            "wifi_good_dbm": spin("wifi_good_dbm", -100, 0, " dBm"),
            "wifi_opacity": spin("wifi_opacity", 0, 100, " %", 10),
        }
        self.wifi_clip = QCheckBox(tr("Clip the Wi-Fi map to the rooms"))
        self.wifi_clip.setChecked(cfg["wifi_clip_rooms"])

        # Connection test: asks the robot who it is, with the values being edited.
        self.btn_test = QPushButton(tr("Test connection"))
        self.btn_test.clicked.connect(self._test_connection)
        self.lbl_test = QLabel()
        self.lbl_test.setWordWrap(True)
        self._test_client = None

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        tabs = QTabWidget()
        form = self._tab(tabs, tr("Connection"))
        form.addRow(tr("Robot address"), self.url)
        form.addRow(tr("Authentication (optional)"), self.auth)
        form.addRow(tr("Live tracking refresh"), self.interval)
        test_row = QHBoxLayout()
        test_row.addWidget(self.btn_test)
        test_row.addWidget(self.lbl_test, 1)
        form.addRow(test_row)

        form = self._tab(tabs, tr("Camera"))
        form.addRow(tr("Camera stream URL"), self.camera_url)
        form.addRow(tr("ffmpeg path"), self.ffmpeg)
        form.addRow(tr("Video width"), self.camera_width)

        form = self._tab(tabs, tr("Notifications"))
        form.addRow(self.notify_dock)

        form = self._tab(tabs, tr("Wi-Fi survey"))
        wifi_labels = {
            "wifi_interval_s": tr("Time between readings"),
            "wifi_min_step_cm": tr("Minimum distance between points"),
            "wifi_max_pos_age_s": tr("Maximum age of the robot position"),
            "wifi_pixel_cm": tr("Map cell size"),
            "wifi_idw_power": tr("IDW distance coefficient"),
            "wifi_bad_dbm": tr("Bad signal (red)"),
            "wifi_fair_dbm": tr("Fair signal (yellow)"),
            "wifi_good_dbm": tr("Good signal (green)"),
            "wifi_opacity": tr("Map opacity"),
        }
        for key, widget in self.wifi.items():
            form.addRow(wifi_labels[key], widget)
        form.addRow(self.wifi_clip)

        form = self._tab(tabs, tr("SSH"))
        form.addRow(tr("SSH user (reboot)"), self.ssh_user)
        form.addRow(tr("SSH port (reboot)"), self.ssh_port)
        hint = QLabel(tr("Used only by “Reboot robot (SSH)…”, with your SSH key "
                         "(no password is stored)."))
        hint.setWordWrap(True)
        form.addRow(hint)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        self.resize(480, self.sizeHint().height())

    @staticmethod
    def _tab(tabs, title):
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        tabs.addTab(page, title)
        return form

    def _test_connection(self, *_):
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

    def accept(self):
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
        for key, widget in self.wifi.items():
            s.setValue(f"valetudo/{key}", widget.value())
        s.setValue("valetudo/wifi_clip_rooms", self.wifi_clip.isChecked())
        super().accept()
