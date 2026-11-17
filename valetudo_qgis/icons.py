"""Plugin icons (SVG or PNG files in icons/, named after the action keys)."""

import os

from qgis.PyQt.QtGui import QIcon

ICON_DIR = os.path.join(os.path.dirname(__file__), "icons")
LOGO = "valetudo_logo_small"   # the plugin's own icon: Plugin Manager, menu, panel, Options
RPI_LOGO = "COLOUR-Raspberry-Pi-Symbol-Registered-300x300"   # the Pi block of the panel


def _path(name):
    for ext in (".svg", ".png"):
        path = os.path.join(ICON_DIR, name + ext)
        if os.path.exists(path):
            return path
    return None


def icon(name):
    """QIcon for icons/<name>.svg (or .png), or an empty icon if there is none."""
    path = _path(name)
    return QIcon(path) if path else QIcon()


def has_icon(name):
    return _path(name) is not None
