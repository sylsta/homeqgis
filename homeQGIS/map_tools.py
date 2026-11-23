"""Map tools: draw a cleaning zone, pick a go-to target, pick rooms.

The tools only emit coordinates in the QGIS frame; the plugin converts and
sends them through the client (the Y flip stays in coords.py).
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import Qgis, QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsRectangle
from qgis.gui import QgsMapTool, QgsMapToolEmitPoint, QgsRubberBand

ZONE_COLOR = QColor(31, 120, 180)


class ZoneMapTool(QgsMapTool):
    """Press, drag and release to draw an axis-aligned rectangle."""

    zoneDrawn = pyqtSignal(QgsRectangle)

    def __init__(self, canvas):
        super().__init__(canvas)
        self._start = None
        self._band = QgsRubberBand(canvas, Qgis.GeometryType.Polygon)
        fill = QColor(ZONE_COLOR)
        fill.setAlpha(60)
        self._band.setFillColor(fill)
        self._band.setStrokeColor(ZONE_COLOR)
        self._band.setWidth(2)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _show(self, rect):
        self._band.reset(Qgis.GeometryType.Polygon)
        corners = [
            QgsPointXY(rect.xMinimum(), rect.yMinimum()),
            QgsPointXY(rect.xMaximum(), rect.yMinimum()),
            QgsPointXY(rect.xMaximum(), rect.yMaximum()),
            QgsPointXY(rect.xMinimum(), rect.yMaximum()),
        ]
        for i, pt in enumerate(corners):
            self._band.addPoint(pt, i == len(corners) - 1)  # redraw on the last one

    def canvasPressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = self.toMapCoordinates(event.pos())

    def canvasMoveEvent(self, event):
        if self._start is not None:
            self._show(QgsRectangle(self._start, self.toMapCoordinates(event.pos())))

    def canvasReleaseEvent(self, event):
        if self._start is None or event.button() != Qt.MouseButton.LeftButton:
            return
        rect = QgsRectangle(self._start, self.toMapCoordinates(event.pos()))
        self._start = None
        self._band.reset(Qgis.GeometryType.Polygon)
        self.zoneDrawn.emit(rect)

    def deactivate(self):
        self._start = None
        self._band.reset(Qgis.GeometryType.Polygon)
        super().deactivate()

    def cleanup(self):
        """Remove the rubber band from the canvas (call on plugin unload)."""
        self._band.reset(Qgis.GeometryType.Polygon)
        self.canvas().scene().removeItem(self._band)


class GoToMapTool(QgsMapToolEmitPoint):
    """Click once to pick a target point (left button only)."""

    pointPicked = pyqtSignal(QgsPointXY)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvasClicked.connect(self._on_click)

    def _on_click(self, point, button):
        if button == Qt.MouseButton.LeftButton:
            self.pointPicked.emit(QgsPointXY(point))


class SensorMapTool(QgsMapTool):
    """Left-click to place a Home Assistant sensor, right-click to remove one."""

    placeRequested = pyqtSignal(QgsPointXY)
    removeRequested = pyqtSignal(QgsPointXY)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def canvasReleaseEvent(self, event):
        point = QgsPointXY(self.toMapCoordinates(event.pos()))
        if event.button() == Qt.MouseButton.LeftButton:
            self.placeRequested.emit(point)
        elif event.button() == Qt.MouseButton.RightButton:
            self.removeRequested.emit(point)


class LineMapTool(QgsMapTool):
    """Click a first point, then a second one: emits the line (split a room).

    A preview follows the mouse after the first click; right-click or Esc cancels.
    """

    lineDrawn = pyqtSignal(QgsPointXY, QgsPointXY)
    cancelled = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self._start = None
        self._band = QgsRubberBand(canvas, Qgis.GeometryType.Line)
        self._band.setStrokeColor(QColor(198, 40, 40))
        self._band.setWidth(3)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _show(self, end):
        self._band.reset(Qgis.GeometryType.Line)
        self._band.addPoint(self._start, False)
        self._band.addPoint(end, True)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.toMapCoordinates(event.pos())
        if self._start is None:
            self._start = point
            self._show(point)
            return
        start, self._start = self._start, None
        self._band.reset(Qgis.GeometryType.Line)
        if start.distance(point) > 0:
            self.lineDrawn.emit(QgsPointXY(start), QgsPointXY(point))

    def canvasMoveEvent(self, event):
        if self._start is not None:
            self._show(self.toMapCoordinates(event.pos()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()

    def _cancel(self):
        self._start = None
        self._band.reset(Qgis.GeometryType.Line)
        self.cancelled.emit()

    def deactivate(self):
        self._start = None
        self._band.reset(Qgis.GeometryType.Line)
        super().deactivate()

    def cleanup(self):
        self._band.reset(Qgis.GeometryType.Line)
        self.canvas().scene().removeItem(self._band)


class RoomPickMapTool(QgsMapTool):
    """Click a room of the robot's map: left button ticks or unticks it in the
    Clean tab, right button opens its menu (rename, join, split)."""

    roomClicked = pyqtSignal(str, str, bool, object)   # id, name, right button, global pos

    def __init__(self, canvas, rooms_layer):
        super().__init__(canvas)
        self._rooms_layer = rooms_layer   # callable: the rooms layer, or None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def canvasReleaseEvent(self, event):
        layer = self._rooms_layer()
        if layer is None:
            return
        point = QgsGeometry.fromPointXY(self.toMapCoordinates(event.pos()))
        request = QgsFeatureRequest().setFilterRect(point.boundingBox())
        for feature in layer.getFeatures(request):
            if feature["type"] == "segment" and feature["segment_id"] \
                    and feature.geometry().contains(point):
                right = event.button() == Qt.MouseButton.RightButton
                self.roomClicked.emit(str(feature["segment_id"]), feature["name"] or "",
                                      right, event.globalPos() if hasattr(event, "globalPos")
                                      else event.globalPosition().toPoint())
                return
