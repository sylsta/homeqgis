"""Load the Qt Designer forms of ``ui/`` into existing widgets.

Every form's ``<class>`` is ``ValetudoQgis``: Qt translates its strings in that
context, the same as ``tr()``, so one ``.ts`` file covers code and forms.
"""

import os

from qgis.PyQt import uic

UI_DIR = os.path.join(os.path.dirname(__file__), "ui")


def load_ui(name, widget, required=()):
    """Build ``ui/<name>`` into ``widget``; its named children become attributes.

    ``required`` lists the object names the Python code uses: a form edited in
    Qt Designer that lost one fails here, with a clear message, rather than
    later on an AttributeError.
    """
    path = os.path.join(UI_DIR, name)
    uic.loadUi(path, widget)
    missing = [n for n in required if getattr(widget, n, None) is None]
    if missing:
        raise RuntimeError(f"{name}: missing object(s) {', '.join(missing)}")
