"""Plugin icons (SVG or PNG files in icons/, named after the action keys)."""

import os

from qgis.PyQt.QtCore import QByteArray, Qt
from qgis.PyQt.QtGui import QIcon, QPainter, QPalette, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import QApplication

ICON_DIR = os.path.join(os.path.dirname(__file__), "icons")
LOGO = "valetudo_logo_small"   # the plugin's own icon: Plugin Manager, menu, panel, Options
RPI_LOGO = "COLOUR-Raspberry-Pi-Symbol-Registered-300x300"   # the Pi block of the panel
HA_LOGO = "HA-lockup-stacked-color-on-dark"   # Home Assistant, in the panel's strip
# Single-colour icons are drawn in this grey: it is replaced by the theme's text
# colour when they are loaded, so they stay visible in a dark theme.
THEMED_COLOR = "#4a4a4a"
THEMED_SIZE = 64   # rendered this large, then scaled down by Qt: sharp on HiDPI


def _path(name):
    for ext in (".svg", ".png"):
        path = os.path.join(ICON_DIR, name + ext)
        if os.path.exists(path):
            return path
    return None


def _themed(path):
    """QIcon of a single-colour SVG, drawn in the theme's text colour (or None)."""
    with open(path, encoding="utf-8") as f:
        svg = f.read()
    if THEMED_COLOR not in svg:
        return None
    app = QApplication.instance()
    if app is None:
        return None
    color = app.palette().color(QPalette.ColorRole.WindowText).name()
    renderer = QSvgRenderer(QByteArray(svg.replace(THEMED_COLOR, color).encode("utf-8")))
    if not renderer.isValid():
        return None
    pixmap = QPixmap(THEMED_SIZE, THEMED_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def icon(name):
    """QIcon for icons/<name>.svg (or .png), or an empty icon if there is none.
    Single-colour icons follow the theme (see THEMED_COLOR)."""
    path = _path(name)
    if not path:
        return QIcon()
    if path.endswith(".svg"):
        try:
            themed = _themed(path)
        except Exception:   # any rendering problem: the icon as drawn
            themed = None
        if themed is not None:
            return themed
    return QIcon(path)


def has_icon(name):
    return _path(name) is not None
