"""The user manual: built from docs/ by MkDocs (see mkdocs.yml), copied into the
plugin's doc/ folder by the build, and published on GitHub Pages.

open_manual() opens the copy inside the plugin, else (e.g. a development install,
where it is not built) the online one.
"""

import os

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

ONLINE = "https://sylsta.github.io/homeqgis/"
LOCAL = os.path.join(os.path.dirname(__file__), "doc")


def manual_url(page="index.html"):
    path = os.path.join(LOCAL, page)
    if os.path.exists(path):
        return QUrl.fromLocalFile(path)
    return QUrl(ONLINE + page)


def open_manual(page="index.html"):
    """Open a page of the manual (e.g. "home.html") in the system's browser."""
    QDesktopServices.openUrl(manual_url(page))
