"""Robot history files: one GeoPackage per day, <project home>/history/robot_YYYY-MM-DD.gpkg,
with three layers:

    outings   (lines)   one per outing: from leaving the dock to coming back
    segments  (lines)   one per continuous activity within an outing
    points    (points)  the readings

Same local frame as the robot's map layers (centimetres, no CRS). The records
come from history_logic.OutingTracker. An outing that crosses midnight is
written to the file of the day it started.
"""

import os
from datetime import datetime

from qgis.PyQt.QtCore import QDateTime, QMetaType
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsFeature, QgsField, QgsFields,
                       QgsGeometry, QgsPointXY, QgsProject, QgsVectorFileWriter,
                       QgsVectorLayer)

FOLDER = "history"
PREFIX = "robot_"

_T = QMetaType.Type
POINT_FIELDS = [("time", _T.QDateTime), ("activity", _T.QString), ("detail", _T.QString),
                ("job_type", _T.QString), ("state", _T.QString), ("battery", _T.Int),
                ("wifi_dbm", _T.Int), ("outing", _T.QString), ("source", _T.QString)]
SEGMENT_FIELDS = [("outing", _T.QString), ("activity", _T.QString), ("detail", _T.QString),
                  ("job_type", _T.QString), ("scheduled", _T.Bool), ("start", _T.QDateTime),
                  ("end", _T.QDateTime), ("duration_s", _T.Int), ("distance_m", _T.Double),
                  ("source", _T.QString)]
OUTING_FIELDS = [("outing", _T.QString), ("start", _T.QDateTime), ("end", _T.QDateTime),
                 ("duration_s", _T.Int), ("distance_m", _T.Double), ("activities", _T.QString),
                 ("job_type", _T.QString), ("scheduled", _T.Bool), ("rooms", _T.QString),
                 ("area_m2", _T.Double), ("result", _T.QString), ("map_id", _T.QString)]
LAYERS = {"outings": (OUTING_FIELDS, Qgis.WkbType.LineString),
          "segments": (SEGMENT_FIELDS, Qgis.WkbType.LineString),
          "points": (POINT_FIELDS, Qgis.WkbType.Point)}


def history_folder(project=None):
    """<project home>/history, or None while the project has never been saved."""
    project = project or QgsProject.instance()
    if not project.fileName():
        return None
    return os.path.join(project.homePath(), FOLDER)


def day_path(folder, t):
    """File of the day of Unix time t (local date)."""
    return os.path.join(folder, f"{PREFIX}{datetime.fromtimestamp(t):%Y-%m-%d}.gpkg")


def _qdatetime(t):
    return QDateTime.fromMSecsSinceEpoch(int(round(t * 1000))) if t is not None else None


def _fields(spec):
    fields = QgsFields()
    for name, kind in spec:
        fields.append(QgsField(name, kind))
    return fields


def _line(points):
    """A line, or no geometry when there are fewer than two points."""
    points = list(points or [])
    if len(points) < 2:
        return QgsGeometry()
    return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points])


class HistoryStore:
    """Writes records to the day files (creating them, with their three layers)."""

    def __init__(self):
        self._layers = {}   # (path, layer name) -> QgsVectorLayer opened on the file

    def _create(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        context = QgsProject.instance().transformContext()
        for index, (name, (spec, geometry)) in enumerate(LAYERS.items()):
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = name
            options.actionOnExistingFile = (
                QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile if index == 0
                else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
            writer = QgsVectorFileWriter.create(path, _fields(spec), geometry,
                                                QgsCoordinateReferenceSystem(), context, options)
            if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
                raise OSError(writer.errorMessage())
            del writer   # closes the file

    def _layer(self, path, name):
        key = (path, name)
        layer = self._layers.get(key)
        if layer is None or not layer.isValid():
            if not os.path.exists(path):
                self._create(path)
            layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
            if not layer.isValid():
                raise OSError(f"cannot open {path} ({name})")
            self._layers[key] = layer
        return layer

    def close(self):
        self._layers.clear()

    def _add(self, path, name, features):
        if not features:
            return
        layer = self._layer(path, name)
        ok, _added = layer.dataProvider().addFeatures(features)
        if not ok:
            raise OSError(f"cannot write to {path} ({name})")

    def write(self, folder, points=(), segments=(), outings=(), outing_days=None):
        """Append records. Each goes to the file of its outing's first day
        (outing_days: outing id -> Unix start time), so that an outing that crosses
        midnight stays in one file."""
        outing_days = outing_days or {}

        def path_of(record):
            return day_path(folder, outing_days.get(record["outing"], record.get("start")
                                                    or record.get("time")))
        by_path = {}
        for point in points:
            f = QgsFeature(_fields(POINT_FIELDS))
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*point["pos"])))
            f.setAttributes([_qdatetime(point["time"]), point["activity"], point["detail"],
                             point["job_type"], point["state"], point["battery"],
                             point["wifi_dbm"], point["outing"], point["source"]])
            by_path.setdefault((path_of(point), "points"), []).append(f)
        for segment in segments:
            f = QgsFeature(_fields(SEGMENT_FIELDS))
            f.setGeometry(_line(segment["geometry"]))
            f.setAttributes([segment["outing"], segment["activity"], segment["detail"],
                             segment["job_type"], segment["scheduled"],
                             _qdatetime(segment["start"]), _qdatetime(segment["end"]),
                             segment["duration_s"], segment["distance_m"],
                             segment.get("source", "live")])
            by_path.setdefault((path_of(segment), "segments"), []).append(f)
        for outing in outings:
            f = QgsFeature(_fields(OUTING_FIELDS))
            f.setGeometry(_line(outing.get("geometry")))
            f.setAttributes([outing["outing"], _qdatetime(outing["start"]),
                             _qdatetime(outing["end"]), outing["duration_s"],
                             outing["distance_m"], ",".join(outing["activities"]),
                             outing["job_type"], outing["scheduled"],
                             ", ".join(outing["rooms"]), outing.get("area_m2"),
                             outing["result"], outing["map_id"]])
            by_path.setdefault((day_path(folder, outing["start"]), "outings"), []).append(f)
        written = []
        for (path, name), features in by_path.items():
            self._add(path, name, features)
            if path not in written:
                written.append(path)
        return written
