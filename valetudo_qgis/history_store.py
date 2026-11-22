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
from datetime import datetime, timedelta

from qgis.PyQt.QtCore import QDateTime, QMetaType
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsFeature, QgsFeatureRequest,
                       QgsField, QgsFields, QgsGeometry, QgsPointXY, QgsProject, QgsVectorFileWriter,
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
                 ("area_m2", _T.Double), ("result", _T.QString), ("map_id", _T.QString),
                 ("source", _T.QString)]
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
            # Files written by an older version: add the fields they lack
            spec = LAYERS[name][0]
            missing = [QgsField(n, kind) for n, kind in spec if layer.fields().indexOf(n) < 0]
            if missing:
                layer.dataProvider().addAttributes(missing)
                layer.updateFields()
            self._layers[key] = layer
        return layer

    def close(self):
        self._layers.clear()

    def _add(self, path, name, records):
        """records: (geometry, {field: value}). Set by name: the file's layers also
        have their "fid" column."""
        if not records:
            return
        layer = self._layer(path, name)
        fields = layer.fields()
        features = []
        for geometry, values in records:
            feature = QgsFeature(fields)
            feature.setGeometry(geometry)
            for field, value in values.items():
                if fields.indexOf(field) >= 0:
                    feature.setAttribute(field, value)
            features.append(feature)
        ok, _added = layer.dataProvider().addFeatures(features)
        if not ok:
            raise OSError(f"cannot write to {path} ({name})")

    def replace_segments(self, folder, outing_id, segments, outing_days=None):
        """Replace the segments of an outing already written (their precise line once
        the outing is over) by segments."""
        start = (outing_days or {}).get(outing_id) or min(s["start"] for s in segments)
        path = day_path(folder, start)
        if os.path.exists(path):
            layer = self._layer(path, "segments")
            request = QgsFeatureRequest().setFilterExpression(
                "\"outing\" = '{}'".format(str(outing_id).replace("'", "''")))
            request.setNoAttributes().setFlags(QgsFeatureRequest.Flag.NoGeometry)
            ids = [f.id() for f in layer.getFeatures(request)]
            if ids and not layer.dataProvider().deleteFeatures(ids):
                raise OSError(f"cannot write to {path} (segments)")
        return self.write(folder, segments=segments,
                          outing_days={outing_id: start})

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
            values = {name: point.get(name) for name, _kind in POINT_FIELDS}
            values["time"] = _qdatetime(point["time"])
            values["source"] = point.get("source") or "live"
            by_path.setdefault((path_of(point), "points"), []).append(
                (QgsGeometry.fromPointXY(QgsPointXY(*point["pos"])), values))
        for segment in segments:
            values = {name: segment.get(name) for name, _kind in SEGMENT_FIELDS}
            values.update(start=_qdatetime(segment["start"]), end=_qdatetime(segment["end"]),
                          source=segment.get("source") or "live")
            by_path.setdefault((path_of(segment), "segments"), []).append(
                (_line(segment.get("geometry")), values))
        for outing in outings:
            values = {name: outing.get(name) for name, _kind in OUTING_FIELDS}
            values.update(start=_qdatetime(outing["start"]), end=_qdatetime(outing["end"]),
                          activities=",".join(outing.get("activities") or []),
                          rooms=", ".join(outing.get("rooms") or []),
                          source=outing.get("source") or "live")
            by_path.setdefault((day_path(folder, outing["start"]), "outings"), []).append(
                (_line(outing.get("geometry")), values))
        written = []
        for (path, name), features in by_path.items():
            self._add(path, name, features)
            if path not in written:
                written.append(path)
        return written


def _plain(value):
    """A feature attribute as plain Python (None for NULL, Unix time for a date)."""
    if value is None or (hasattr(value, "isNull") and value.isNull()):
        return None
    if isinstance(value, QDateTime):
        return value.toMSecsSinceEpoch() / 1000
    return value


def read_outings(path):
    """The outings of one day file, oldest first (empty if there is none). Each also
    has "extent" (QgsRectangle or None)."""
    if not os.path.exists(path):
        return []
    layer = QgsVectorLayer(f"{path}|layername=outings", "outings", "ogr")
    if not layer.isValid():
        return []
    names = layer.fields().names()
    outings = []
    for feature in layer.getFeatures():
        record = {name: _plain(feature[name]) for name in names}
        record["extent"] = feature.geometry().boundingBox() if feature.hasGeometry() else None
        outings.append(record)
    del layer
    return sorted(outings, key=lambda o: o.get("start") or 0)


def recorded_intervals(folder, start, end):
    """(start, end) of the outings recorded in the day files from Unix time start to end
    (one day of margin on each side)."""
    intervals = []
    day = datetime.fromtimestamp(start).date() - timedelta(days=1)
    last = datetime.fromtimestamp(end).date() + timedelta(days=1)
    while day <= last:
        path = day_path(folder, datetime(day.year, day.month, day.day, 12).timestamp())
        intervals += [(o["start"], o["end"]) for o in read_outings(path)
                      if o.get("start") and o.get("end")]
        day += timedelta(days=1)
    return intervals
