"""A small status card over the map canvas (state, battery, job in progress).

Shown while "Show on map" is on, in the canvas's top right corner, so the robot
can be watched with the panel closed. It does not take mouse clicks.
"""

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtWidgets import QLabel

MARGIN = 10


class MapOverlay(QObject):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.card = QLabel(canvas)
        self.card.setTextFormat(Qt.TextFormat.RichText)
        self.card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.card.setStyleSheet(
            "QLabel { background-color: rgba(255, 255, 255, 215); color: #212121;"
            " border: 1px solid rgba(0, 0, 0, 60); border-radius: 6px; padding: 4px 8px; }")
        self.card.hide()
        canvas.installEventFilter(self)

    def set_html(self, html):
        self.card.setText(html)
        self.card.adjustSize()
        self._place()

    def set_visible(self, visible):
        self.card.setVisible(visible and bool(self.card.text()))
        self._place()

    def _place(self):
        self.card.move(max(MARGIN, self.canvas.width() - self.card.width() - MARGIN), MARGIN)
        self.card.raise_()

    def eventFilter(self, obj, event):
        if obj is self.canvas and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def remove(self):
        self.canvas.removeEventFilter(self)
        self.card.deleteLater()
