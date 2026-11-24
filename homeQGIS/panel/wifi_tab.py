"""Wi-Fi tab of the panel: live signal, thresholds, recorders."""

import html

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.core import QgsSettings

from ..core.i18n import tr
from ..core.settings import load_settings
from .widgets import Sparkline, signal_color

class WifiMixin:
    """Part of ValetudoPanel (see status_panel.py)."""

    def _build_wifi(self):
        """Wi-Fi."""
        self.sparkline = Sparkline()
        self.sparkline_layout.addWidget(self.sparkline)
        cfg = load_settings()
        for name, key in (("spin_wifi_good", "wifi_good_dbm"), ("spin_wifi_fair", "wifi_fair_dbm"),
                          ("spin_wifi_bad", "wifi_bad_dbm")):
            spin = getattr(self, name)
            spin.setValue(int(cfg[key]))
            spin.valueChanged.connect(lambda value, k=key: self._on_threshold(k, value))
        self._update_thresholds()
        self.btn_pi_latest.clicked.connect(lambda: self.piMapRequested.emit(False))
        self.btn_pi_full.clicked.connect(lambda: self.piMapRequested.emit(True))
        self.lbl_pi_thumb.setVisible(False)

    def _on_threshold(self, key, value):
        QgsSettings().setValue(f"valetudo/{key}", value)
        self._update_thresholds()

    def _update_thresholds(self):
        self.sparkline.thresholds = (self.spin_wifi_good.value(), self.spin_wifi_fair.value(),
                                     self.spin_wifi_bad.value())
        self.sparkline.update()

    def set_robot_recorder_status(self, text):
        """Called by the plugin: where the Wi-Fi recorder of the robot stands."""
        self.lbl_robot_recorder.setText(text)

    def set_pi_thumbnail(self, path):
        """Called by the plugin with the PNG of the last map loaded from the Pi."""
        pixmap = QPixmap(path) if path else QPixmap()
        self.lbl_pi_thumb.setVisible(not pixmap.isNull())
        if not pixmap.isNull():
            self.lbl_pi_thumb.setPixmap(pixmap.scaledToWidth(
                min(260, pixmap.width()), Qt.TransformationMode.SmoothTransformation))

    def _on_wifi(self, wifi):
        """Wi-Fi signal in the header, coloured with the Wi-Fi survey thresholds;
        network name, band and address in its tooltip."""
        details = (wifi or {}).get("details") or {}
        signal = details.get("signal")
        if signal is None:
            self._wifi_html, self._wifi_tip = "", ""
            self._update_strip_tip()
        else:
            cfg = load_settings()
            color = signal_color(signal, cfg["wifi_good_dbm"], cfg["wifi_fair_dbm"],
                                 cfg["wifi_bad_dbm"])
            text = tr("Wi-Fi {signal} dBm").format(signal=signal)
            self.sparkline.add(signal)
            self._wifi_html = f"<span style='color:{color}'>{html.escape(text)}</span>"
            parts = [details.get("ssid"), details.get("frequency"),
                     (details.get("ips") or [None])[0]]
            self._robot_ip = (details.get("ips") or [""])[0] or ""
            self._update_robot_info()
            self._wifi_tip = tr("Wi-Fi: {details}").format(
                details=" · ".join(str(p) for p in parts if p) or "—")
            self._update_strip_tip()
            self.lbl_wifi_now.setText(" · ".join(
                [f"<b style='color:{color}'>{signal} dBm</b>"]
                + [html.escape(str(p)) for p in parts if p]))
        self._update_robot_label()
