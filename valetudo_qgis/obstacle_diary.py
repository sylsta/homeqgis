"""Every obstacle the robot reports, kept: the map only shows the current ones.

Each obstacle Valetudo puts on the map (an id per sighting: its type and place)
becomes a point of the "Obstacle diary" layer (map/obstacle_diary.gpkg): kind,
confidence, first and last seen, and its photo, fetched once and kept in
map/obstacles/<id>.jpg. Points pile up where things are often left: the
semi-transparent symbols darken there.
"""

import os
import time

from qgis.PyQt.QtCore import QDateTime, QMetaType, QObject
from qgis.core import (QgsAction, QgsField, QgsGeometry, QgsMarkerSymbol,
                       QgsSingleSymbolRenderer)

from .coords import v2q
from .i18n import tr
from .map_layers import parse_obstacle
from .project_layers import kept_layer, new_feature, project_folder

FOLDER = "map"
FILE = "obstacle_diary.gpkg"
PHOTOS = "obstacles"
ROLE = "map/obstacle_diary"
LAST_SEEN_EVERY_S = 600   # "last seen" written at most this often per obstacle


def style_diary(layer):
    symbol = QgsMarkerSymbol.createSimple({"name": "circle", "color": "255,111,0,90",
                                           "outline_style": "no", "size": "5"})
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setMapTipTemplate('<b>[% "kind" %]</b> ([% "confidence" %] %)<br>'
                            '[% "first_seen" %]<br>'
                            '[% CASE WHEN "photo_file" IS NOT NULL THEN '
                            '\'<img src="file:///\' || "photo_file" || \'" width="320">\' '
                            'END %]')
    action = QgsAction(QgsAction.ActionType.OpenUrl, tr("Open the photo"),
                       '[% "photo_file" %]', "", False, "", {"Feature", "Canvas"})
    layer.actions().addAction(action)


class ObstacleDiary(QObject):
    def __init__(self, project, get_client, parent=None):
        super().__init__(parent)
        self.project, self.get_client = project, get_client
        self._layer_id = None
        self._known = None       # obstacle id -> (feature id, last "last seen" write)
        self._fetching = set()

    def on_map(self, map_json):
        obstacles = [e for e in (map_json or {}).get("entities", [])
                     if e.get("type") == "obstacle" and len(e.get("points") or []) >= 2]
        folder = project_folder(FOLDER)
        if not obstacles or folder is None:
            return
        layer = self._layer(folder)
        now, stamp = time.monotonic(), QDateTime.currentDateTime()
        new, seen_again = [], {}
        for entity in obstacles:
            values = parse_obstacle(entity.get("metaData") or {})
            oid = values.get("obstacle_id")
            if not oid:
                continue
            if oid in self._known:
                fid, written = self._known[oid]
                if now - written >= LAST_SEEN_EVERY_S:
                    seen_again[fid] = oid
                continue
            pts = entity["points"]
            values.update(first_seen=stamp, last_seen=stamp, photo_file=None)
            new.append((oid, values["photo"], new_feature(
                layer, QgsGeometry.fromPointXY(v2q(pts[0], pts[1])), values)))
        if new:
            ok, added = layer.dataProvider().addFeatures([f for _o, _p, f in new])
            if ok:
                for (oid, photo, _f), feature in zip(new, added):
                    self._known[oid] = (feature.id(), now)
                    if photo:
                        self._fetch_photo(oid, feature.id(), folder)
        if seen_again:
            index = layer.fields().indexOf("last_seen")
            layer.dataProvider().changeAttributeValues(
                {fid: {index: stamp} for fid in seen_again})
            for fid, oid in seen_again.items():
                self._known[oid] = (fid, now)
        if new or seen_again:
            layer.updateExtents()
            layer.triggerRepaint()

    def _fetch_photo(self, oid, fid, folder):
        client = self.get_client()
        if client is None or oid in self._fetching:
            return
        self._fetching.add(oid)

        def save(data):
            self._fetching.discard(oid)
            if not data:
                return
            path = os.path.join(folder, PHOTOS, f"{oid}.jpg")
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(data)
            except OSError:
                return
            layer = self._layer(folder)
            layer.dataProvider().changeAttributeValues(
                {fid: {layer.fields().indexOf("photo_file"): path}})

        client.fetch_obstacle_image(oid, save, lambda _e: self._fetching.discard(oid))

    def _layer(self, folder):
        layer = self.project.mapLayer(self._layer_id) if self._layer_id else None
        if layer is None:
            layer = kept_layer(self.project, ROLE, tr("Obstacle diary"), "Point", [
                QgsField("kind", QMetaType.Type.QString),
                QgsField("confidence", QMetaType.Type.Int),
                QgsField("label", QMetaType.Type.QString),
                QgsField("obstacle_id", QMetaType.Type.QString),
                QgsField("photo", QMetaType.Type.Int),
                QgsField("photo_file", QMetaType.Type.QString),
                QgsField("first_seen", QMetaType.Type.QDateTime),
                QgsField("last_seen", QMetaType.Type.QDateTime),
            ], folder, FILE, "diary", style_diary)
            self._layer_id = layer.id()
            self._known = {}
            index = layer.fields().indexOf("obstacle_id")
            for feature in layer.getFeatures():
                if feature[index]:
                    self._known[str(feature[index])] = (feature.id(), 0.0)
        return layer
