"""What the robot saw, on the map: while the camera plays and the robot is out, a
frame every VIEW_STEP_CM, placed where the robot was, facing where it looked.

The images go to views/<date>/<time>.jpg next to the project, the points to the
"Camera views" layer (views/camera_views.gpkg): time, file, heading. Hovering a
point (map tips on) shows the image; its action opens it full size.
"""

import os
import time

from qgis.PyQt.QtCore import QDateTime, QMetaType, QObject
from qgis.core import QgsAction, QgsField, QgsGeometry, QgsMarkerSymbol, QgsProperty, \
    QgsSingleSymbolRenderer

from ..core.coords import v2q
from ..core.i18n import tr
from ..core.project_layers import kept_layer, new_feature, project_folder

VIEWS_FOLDER = "views"
VIEWS_FILE = "camera_views.gpkg"
ROLE = "views/camera"
VIEW_STEP_CM = 100       # a frame every metre the robot moves…
MIN_INTERVAL_S = 2       # …at most every 2 s
MAX_POSITION_AGE_S = 5   # the position must be this fresh


def views_folder():
    return project_folder(VIEWS_FOLDER)


def style_views(layer):
    """A small camera-coloured triangle pointing where the robot looked; the image in
    the map tip; an action opening it."""
    symbol = QgsMarkerSymbol.createSimple({"name": "triangle", "color": "#00838f",
                                           "outline_color": "white", "size": "3"})
    symbol.setDataDefinedAngle(QgsProperty.fromExpression('coalesce("heading", 0)'))
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setMapTipTemplate('<b>[% "time" %]</b><br>'
                            '<img src="file:///[% "file" %]" width="360">')
    action = QgsAction(QgsAction.ActionType.OpenUrl, tr("Open the image"),
                       '[% "file" %]', "", False, "", {"Feature", "Canvas"})
    layer.actions().addAction(action)


class CameraViews(QObject):
    def __init__(self, project, robot_out, enabled, parent=None):
        """robot_out(): True while the robot is away from its dock; enabled(): the
        setting (read only when a view would be kept)."""
        super().__init__(parent)
        self.project, self.robot_out, self.enabled = project, robot_out, enabled
        self._pos = None          # (QgsPointXY, heading, time.monotonic())
        self._last = None         # (QgsPointXY, time.monotonic()) of the last view kept
        self._layer_id = None

    def on_map(self, map_json):
        for ent in (map_json or {}).get("entities", []):
            pts = ent.get("points") or []
            if ent.get("type") == "robot_position" and len(pts) >= 2:
                angle = (ent.get("metaData") or {}).get("angle")
                self._pos = (v2q(pts[0], pts[1]), angle, time.monotonic())
                return

    def on_jpeg(self, jpeg):
        if self._pos is None or not self.robot_out():
            return
        position, heading, seen = self._pos
        now = time.monotonic()
        if now - seen > MAX_POSITION_AGE_S:
            return
        if self._last is not None and (now - self._last[1] < MIN_INTERVAL_S
                                       or self._last[0].distance(position) < VIEW_STEP_CM):
            return
        folder = views_folder()
        if folder is None or not self.enabled():
            return   # never saved: nowhere to keep the images (or not wanted)
        stamp = QDateTime.currentDateTime()
        day = os.path.join(folder, stamp.toString("yyyy-MM-dd"))
        os.makedirs(day, exist_ok=True)
        path = os.path.join(day, stamp.toString("HHmmss_zzz") + ".jpg")
        try:
            with open(path, "wb") as handle:
                handle.write(jpeg)
        except OSError:
            return
        layer = self._layer(folder)
        layer.dataProvider().addFeatures([new_feature(
            layer, QgsGeometry.fromPointXY(position),
            {"time": stamp, "file": path,
             "heading": float(heading) if isinstance(heading, (int, float)) else None})])
        layer.updateExtents()
        layer.triggerRepaint()
        self._last = (position, now)

    def _layer(self, folder):
        layer = self.project.mapLayer(self._layer_id) if self._layer_id else None
        if layer is None:
            layer = kept_layer(self.project, ROLE, tr("Camera views"), "Point",
                               [QgsField("time", QMetaType.Type.QDateTime),
                                QgsField("file", QMetaType.Type.QString),
                                QgsField("heading", QMetaType.Type.Double)],
                               folder, VIEWS_FILE, "views", style_views)
            self._layer_id = layer.id()
        return layer

