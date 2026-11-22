"""Wi-Fi survey: record the robot's Wi-Fi signal where it stands, then map it.

While recording, a timer asks the robot for its Wi-Fi status and its map (for
the position). Each signal reading is stored as a point at the latest robot
position, provided that position is recent and far enough from the previous
sample. ``build_wifi_map()`` interpolates the points (IDW) into a raster,
optionally clipped to the rooms, styled with fixed dBm thresholds so that two
surveys can be compared.

All tuning values come from the settings (see ``settings.py``, edited in Settings › Options).
"""

import os
import time

from qgis.PyQt.QtCore import QDateTime, QMetaType, QObject, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis, QgsColorRampShader, QgsCoordinateReferenceSystem, QgsFeatureRequest, QgsField, QgsGeometry,
    QgsProperty, QgsRasterLayer, QgsRasterShader, QgsSingleBandPseudoColorRenderer,
    QgsSymbol, QgsSymbolLayer, QgsVectorLayer,
)

from .coords import v2q
from .i18n import tr
from .project_layers import adopt, make_permanent, new_feature, project_folder, tag

WIFI_FOLDER = "wifi"
WIFI_FILE = "robot_wifi.gpkg"        # the survey points (layer "points")
WIFI_RASTER = "robot_wifi_signal.tif"
IDW_ALGORITHM = "qgis:idwinterpolation"   # from the Processing plugin
ROLE = "wifi/points"
ENGLISH_NAME = "Wi-Fi survey"


def wifi_folder():
    """<project folder>/wifi, or None while the project has never been saved."""
    return project_folder(WIFI_FOLDER)

# Colours of the fixed thresholds: bad, fair, good.
COLOR_BAD, COLOR_FAIR, COLOR_GOOD = "#d7191c", "#fdd835", "#1a9641"


def layer_names():
    return {"points": tr("Wi-Fi survey"), "map": tr("Wi-Fi signal (dBm)")}


def _robot_position(map_json):
    for ent in (map_json or {}).get("entities", []):
        pts = ent.get("points") or []
        if ent.get("type") == "robot_position" and len(pts) >= 2:
            return v2q(pts[0], pts[1])
    return None


class WifiSurvey(QObject):
    """Records (position, signal) samples into a point layer of the project."""

    sampleAdded = pyqtSignal(int)   # number of points in the layer

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.client = None
        self.cfg = {}
        self._layer_id = None
        self._pos, self._pos_t, self._last = None, 0.0, None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # -- layer ----------------------------------------------------------------------

    def layer(self):
        """The survey layer, or None if there is none in the project (found again in a
        reopened project by its role tag)."""
        lyr = self.project.mapLayer(self._layer_id) if self._layer_id else None
        if lyr is None:
            lyr = adopt(self.project, ROLE, {layer_names()["points"], ENGLISH_NAME},
                        Qgis.GeometryType.Point)
            self._layer_id = lyr.id() if lyr is not None else None
        return lyr

    def persist(self):
        """Once the project is saved, the points go to wifi/robot_wifi.gpkg.
        Raises OSError."""
        folder = wifi_folder()
        if folder is None:
            return False
        return make_permanent(self.layer(), os.path.join(folder, WIFI_FILE), "points")

    def _ensure_layer(self):
        lyr = self.layer()
        if lyr is not None:   # keep adding to it: several runs give a smoother map
            style_wifi_points(lyr, self.cfg)   # thresholds may have changed
            return lyr
        lyr = QgsVectorLayer("Point", layer_names()["points"], "memory")
        lyr.setCrs(QgsCoordinateReferenceSystem())
        lyr.dataProvider().addAttributes([
            QgsField("signal", QMetaType.Type.Int),
            QgsField("frequency", QMetaType.Type.QString),
            QgsField("ssid", QMetaType.Type.QString),
            QgsField("time", QMetaType.Type.QDateTime),
        ])
        lyr.updateFields()
        tag(lyr, ROLE)
        style_wifi_points(lyr, self.cfg)
        self.project.addMapLayer(lyr, False)
        self.project.layerTreeRoot().insertLayer(0, lyr)
        lyr.setCrs(QgsCoordinateReferenceSystem())   # undo any default CRS
        self._layer_id = lyr.id()
        try:
            self.persist()
        except OSError:
            pass   # stays a memory layer; tried again when the project is saved
        return lyr

    def add_rows(self, rows, cfg):
        """Add readings recorded on the robot (robot_survey.parse_rows()).

        A reading already in the layer (same time, to the second) is skipped,
        so importing the robot's file again only adds the new ones.
        Returns the number of points added."""
        if not self.is_running():
            self.cfg = cfg
        lyr = self._ensure_layer()
        idx = lyr.fields().indexOf("time")
        known = set()
        for feature in lyr.getFeatures():
            value = feature[idx]
            if isinstance(value, QDateTime) and value.isValid():
                known.add(value.toSecsSinceEpoch())
        features = []
        for row in rows:
            if row["time"] in known:
                continue
            known.add(row["time"])
            features.append(new_feature(
                lyr, QgsGeometry.fromPointXY(v2q(row["x"], row["y"])),
                {"signal": int(row["signal"]), "frequency": row.get("frequency", ""),
                 "ssid": row.get("ssid", ""),
                 "time": QDateTime.fromSecsSinceEpoch(int(row["time"]))}))
        if features:
            lyr.dataProvider().addFeatures(features)
            lyr.updateExtents()
            lyr.triggerRepaint()
        return len(features)

    # -- recording ------------------------------------------------------------------

    def is_running(self):
        return self._timer.isActive()

    def start(self, client, cfg):
        self.stop()
        self.client, self.cfg = client, cfg
        self._pos, self._pos_t, self._last = None, 0.0, None
        self._ensure_layer()
        client.mapReceived.connect(self._on_map)
        client.mapPeeked.connect(self._on_map)
        client.wifiReceived.connect(self._on_wifi)
        self._timer.start(int(cfg["wifi_interval_s"] * 1000))
        self._tick()

    def stop(self):
        self._timer.stop()
        if self.client is not None:
            for sig, slot in ((self.client.mapReceived, self._on_map),
                              (self.client.mapPeeked, self._on_map),
                              (self.client.wifiReceived, self._on_wifi)):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self.client = None

    def _tick(self):
        if self.client is None:
            return
        self.client.peek_map()            # position (does not touch the map layers)
        self.client.fetch_wifi(quiet=True)

    def _on_map(self, map_json):
        pos = _robot_position(map_json)
        if pos is not None:
            self._pos, self._pos_t = pos, time.monotonic()

    def _on_wifi(self, wifi):
        details = (wifi or {}).get("details") or {}
        signal = details.get("signal")
        if signal is None or self._pos is None:
            return
        if time.monotonic() - self._pos_t > self.cfg["wifi_max_pos_age_s"]:
            return   # position too old: the robot may have moved since
        if self._last is not None and self._last.distance(self._pos) < self.cfg["wifi_min_step_cm"]:
            return   # robot (almost) still: do not pile up identical samples
        lyr = self.layer()
        if lyr is None:      # removed by the user while recording: start a new one
            lyr = self._ensure_layer()
        f = new_feature(lyr, QgsGeometry.fromPointXY(self._pos),
                        {"signal": int(signal), "frequency": str(details.get("frequency") or ""),
                         "ssid": str(details.get("ssid") or ""),
                         "time": QDateTime.currentDateTime()})
        lyr.dataProvider().addFeatures([f])
        lyr.updateExtents()
        lyr.triggerRepaint()
        self._last = self._pos
        self.sampleAdded.emit(lyr.featureCount())


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------

def _ensure_processing():
    """The interpolation comes from QGIS's Processing plugin. A profile where it is not
    enabled (e.g. a new one, as the app's) has not registered its algorithms:
    initialise Processing here, which works without the plugin's own interface."""
    from qgis.core import QgsApplication
    if QgsApplication.processingRegistry().algorithmById(IDW_ALGORITHM) is not None:
        return
    try:
        from processing.core.Processing import Processing
        Processing.initialize()
    except Exception as exc:   # Processing not installed at all (rare)
        raise RuntimeError(str(exc)) from exc
    if QgsApplication.processingRegistry().algorithmById(IDW_ALGORITHM) is None:
        raise RuntimeError(f"{IDW_ALGORITHM}: enable the Processing plugin "
                           "(Plugins › Manage and Install Plugins)")


def build_wifi_map(points, rooms, cfg, project):
    """Interpolate the survey points into a styled raster layer added to the project.

    Uses the selected points if any (e.g. one Wi-Fi band), otherwise all of them.
    Returns (layer, clipped) or raises ValueError("too_few_points") /
    RuntimeError(details) if Processing fails.
    """
    from qgis import processing   # imported late: Processing may be disabled at startup
    _ensure_processing()

    source = points
    if points.selectedFeatureCount() > 0:
        source = points.materialize(
            QgsFeatureRequest().setFilterFids(points.selectedFeatureIds()))
        source.setCrs(QgsCoordinateReferenceSystem())
        project.addMapLayer(source, False)   # Processing finds layers through the project
    try:
        if source.featureCount() < 3:
            raise ValueError("too_few_points")
        field = source.fields().indexOf("signal")
        margin = 2 * cfg["wifi_pixel_cm"]
        extent = source.extent().buffered(margin)
        if rooms is not None and rooms.featureCount():
            extent = rooms.extent().buffered(margin)
        try:
            result = processing.run(IDW_ALGORITHM, {
                "INTERPOLATION_DATA": f"{source.id()}::~::0::~::{field}::~::0",
                "DISTANCE_COEFFICIENT": cfg["wifi_idw_power"],
                "EXTENT": extent,
                "PIXEL_SIZE": cfg["wifi_pixel_cm"],
                "OUTPUT": "TEMPORARY_OUTPUT",
            })
        except Exception as exc:   # QgsProcessingException and friends
            raise RuntimeError(str(exc)) from exc
    finally:
        if source is not points:
            project.removeMapLayer(source.id())

    output, clipped = result["OUTPUT"], False
    if cfg["wifi_clip_rooms"] and rooms is not None and rooms.featureCount():
        try:
            output = processing.run("gdal:cliprasterbymasklayer", {
                "INPUT": output, "MASK": rooms, "NODATA": -9999,
                "CROP_TO_CUTLINE": False, "OUTPUT": "TEMPORARY_OUTPUT",
            })["OUTPUT"]
            clipped = True
        except Exception:   # e.g. GDAL refusing a frame without CRS: keep the full raster
            clipped = False
    folder = wifi_folder()
    if folder is not None:   # saved project: keep the map next to it
        output = _keep_raster(output, os.path.join(folder, WIFI_RASTER))

    raster = QgsRasterLayer(output, layer_names()["map"])
    if not raster.isValid():
        raise RuntimeError(output)
    raster.setCrs(QgsCoordinateReferenceSystem())
    style_wifi_raster(raster, cfg)
    style_wifi_points(points, cfg)
    project.addMapLayer(raster, False)
    root = project.layerTreeRoot()
    root.insertLayer(0, raster)
    node = root.findLayer(points.id())
    if node is not None:   # keep the points above the raster
        clone = node.clone()
        root.insertChildNode(0, clone)
        node.parent().removeChildNode(node)
    return raster, clipped


def _keep_raster(path, target):
    """Copy a temporary GeoTIFF next to the project (the previous map is replaced).
    Returns the path to use (the temporary one if the copy fails)."""
    import shutil
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(path, target)
        return target
    except OSError:
        return path


def style_wifi_points(lyr, cfg):
    """Points coloured with the same thresholds as the raster."""
    symbol = QgsSymbol.defaultSymbol(Qgis.GeometryType.Point)
    symbol.setSize(2.0)
    bad, fair, good = cfg["wifi_bad_dbm"], cfg["wifi_fair_dbm"], cfg["wifi_good_dbm"]
    expr = (f"CASE WHEN \"signal\" <= {fair} "
            f"THEN color_mix_rgb('{COLOR_BAD}', '{COLOR_FAIR}', "
            f"scale_linear(\"signal\", {bad}, {fair}, 0, 1)) "
            f"ELSE color_mix_rgb('{COLOR_FAIR}', '{COLOR_GOOD}', "
            f"scale_linear(\"signal\", {fair}, {good}, 0, 1)) END")
    symbol.symbolLayer(0).setDataDefinedProperty(
        QgsSymbolLayer.Property.FillColor, QgsProperty.fromExpression(expr))
    lyr.renderer().setSymbol(symbol)
    lyr.triggerRepaint()


def style_wifi_raster(raster, cfg):
    """Fixed thresholds (not min/max) so that maps of different surveys compare."""
    bad, fair, good = cfg["wifi_bad_dbm"], cfg["wifi_fair_dbm"], cfg["wifi_good_dbm"]
    ramp = QgsColorRampShader(bad, good)
    ramp.setColorRampType(Qgis.ShaderInterpolationMethod.Linear)
    ramp.setClip(False)   # values beyond the thresholds keep the end colours
    ramp.setColorRampItemList([
        QgsColorRampShader.ColorRampItem(bad, QColor(COLOR_BAD), f"{bad} dBm"),
        QgsColorRampShader.ColorRampItem(fair, QColor(COLOR_FAIR), f"{fair} dBm"),
        QgsColorRampShader.ColorRampItem(good, QColor(COLOR_GOOD), f"{good} dBm"),
    ])
    shader = QgsRasterShader(bad, good)
    shader.setRasterShaderFunction(ramp)
    renderer = QgsSingleBandPseudoColorRenderer(raster.dataProvider(), 1, shader)
    renderer.setClassificationMin(bad)
    renderer.setClassificationMax(good)
    raster.setRenderer(renderer)
    raster.setOpacity(cfg["wifi_opacity"] / 100)
    raster.triggerRepaint()
