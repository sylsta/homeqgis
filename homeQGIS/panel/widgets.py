"""Small widgets of the status panel: signal graph, full-screen video, tab badges."""

import time

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from qgis.PyQt.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..core.i18n import tr

SPARK_SECONDS = 600      # the graph shows the last 10 minutes
SPARK_RANGE = (-90, -30)  # dBm, bottom and top of the graph


def badge_icon(base, color="#ef6c00", size=22):
    """base icon with a coloured dot in its top-right corner (tab badge)."""
    pixmap = base.pixmap(size, size)
    if pixmap.isNull():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("white"), 1.5))
    painter.setBrush(QColor(color))
    r = size * 0.36
    painter.drawEllipse(QRectF(size - r - 1, 1, r, r))
    painter.end()
    return QIcon(pixmap)


def signal_color(signal, good, fair, bad):
    """Colour of a dBm value with the Wi-Fi survey thresholds (as in the header)."""
    if signal >= good:
        return "#2e7d32"
    if signal >= fair:
        return "#9e9d24"
    if signal > bad:
        return "#ef6c00"
    return "#c62828"


class Sparkline(QWidget):
    """The last minutes of Wi-Fi signal, as a line with coloured threshold bands."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = []          # [(time.monotonic(), dBm)]
        self.thresholds = (-50, -67, -80)
        self.setMinimumHeight(48)
        self.setMaximumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(tr("Wi-Fi signal over the last 10 minutes"))

    def add(self, signal):
        now = time.monotonic()
        self.samples.append((now, signal))
        self.samples = [(t, s) for t, s in self.samples if now - t <= SPARK_SECONDS]
        self.update()

    def clear(self):
        self.samples = []
        self.update()

    def _y(self, signal, rect):
        low, high = SPARK_RANGE
        ratio = (min(high, max(low, signal)) - low) / (high - low)
        return rect.bottom() - ratio * rect.height()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 3, -1, -3)
        good, fair, bad = self.thresholds
        # Background bands: red below "bad", orange, yellow, green above "good".
        bands = [(SPARK_RANGE[0], bad, "#c62828"), (bad, fair, "#ef6c00"),
                 (fair, good, "#9e9d24"), (good, SPARK_RANGE[1], "#2e7d32")]
        for low, high, color in bands:
            top, bottom = self._y(high, rect), self._y(low, rect)
            band = QColor(color)
            band.setAlpha(28)
            painter.fillRect(QRectF(rect.left(), top, rect.width(), bottom - top), band)
        if len(self.samples) < 2:
            painter.setPen(QColor("#9e9e9e"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("Waiting for readings…"))
            return
        now = time.monotonic()
        path = QPainterPath()
        for i, (t, s) in enumerate(self.samples):
            x = rect.right() - (now - t) / SPARK_SECONDS * rect.width()
            point = QPointF(x, self._y(s, rect))
            path.moveTo(point) if i == 0 else path.lineTo(point)
        painter.setPen(QPen(QColor(signal_color(self.samples[-1][1], good, fair, bad)), 2))
        painter.drawPath(path)


class VideoWindow(QWidget):
    """The camera picture in its own window, full screen; Esc or a click closes it."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(tr("Valetudo camera"))
        self.setStyleSheet("background-color: black;")
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        self._image = None

    def show_image(self, image):
        self._image = image
        if self.isVisible():
            self.label.setPixmap(QPixmap.fromImage(image).scaled(
                self.label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, _event):
        self.close()
