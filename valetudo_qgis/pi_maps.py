"""Wi-Fi maps built on the Raspberry Pi (pi/valetudo_wifi_collect.py) -> QGIS layers.

Over SSH, the Pi sends a run as a tar archive, its GeoTIFF and its CSV: the
newest run (the one the 'latest.tif' link points to), or the full map of all
runs (wifi_full). They are kept in
the QGIS profile folder (valetudo_wifi_maps/), so a saved project still finds
them, and added to a "Wi-Fi maps (Pi)" group: the map styled with the
plugin's thresholds, the readings as coloured points.

This module has no user-facing text except the layer and group names.
"""

import csv
import io
import os
import re
import tarfile

from qgis.PyQt.QtCore import QDateTime, QMetaType
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsField, QgsGeometry,
    QgsRasterLayer, QgsVectorLayer,
)

from .coords import v2q
from .i18n import tr
from .wifi_survey import style_wifi_points, style_wifi_raster

LOCAL_DIR = "valetudo_wifi_maps"
FULL_NAME = "wifi_full"
RUN_NAME = re.compile(r"^wifi_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})$")


def group_name():
    return tr("Wi-Fi maps (Pi)")


def local_dir():
    path = os.path.join(QgsApplication.qgisSettingsDirPath(), LOCAL_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def fetch_command(folder, full=False):
    """Remote command: tar of the newest run, or of the full map, on stdout.
    Errors go to stderr as error=<key> (no_folder, no_map, no_full_map)."""
    folder = (folder or "valetudo_wifi").strip()
    if folder.startswith("~/"):
        folder = folder[2:]          # ssh starts in the home folder
    quoted = "'" + folder.replace("'", "'\\''") + "'"
    pick = (f'[ -f {FULL_NAME}.tif ] || {{ echo error=no_full_map >&2; exit 3; }}; '
            f"n={FULL_NAME}" if full else
            "n=$(readlink latest.tif) || { echo error=no_map >&2; exit 3; }; n=${n%.tif}")
    return (f"cd {quoted} 2>/dev/null || {{ echo error=no_folder >&2; exit 2; }}; "
            f'{pick}; tar -cf - "$n.tif" "$n.csv" 2>/dev/null; true')


def run_label(name):
    """'wifi_2026-11-17_18-26' -> '2026-11-17 18:26'; the full map -> 'all runs'."""
    if name == FULL_NAME:
        return tr("all runs")
    match = RUN_NAME.match(name)
    if not match:
        return name
    y, mo, d, h, mi = match.groups()
    return f"{y}-{mo}-{d} {h}:{mi}"


def unpack(data):
    """tar bytes -> (run name, local .tif path, local .csv path or None)."""
    target = local_dir()
    tif = csv_path = None
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            base = os.path.basename(member.name)   # never write outside our folder
            if not member.isfile() or not base.startswith("wifi_") \
                    or not base.endswith((".tif", ".csv")):
                continue
            path = os.path.join(target, base)
            with archive.extractfile(member) as src, open(path, "wb") as dst:
                dst.write(src.read())
            if base.endswith(".tif"):
                tif = path
            else:
                csv_path = path
    if tif is None:
        raise ValueError("no_map")
    return os.path.splitext(os.path.basename(tif))[0], tif, csv_path


def points_layer(csv_path, name, cfg):
    """Readings of the CSV as a memory point layer, in the plugin's frame."""
    lyr = QgsVectorLayer("Point", name, "memory")
    lyr.setCrs(QgsCoordinateReferenceSystem())
    lyr.dataProvider().addAttributes([
        QgsField("signal", QMetaType.Type.Int),
        QgsField("frequency", QMetaType.Type.QString),
        QgsField("ssid", QMetaType.Type.QString),
        QgsField("time", QMetaType.Type.QDateTime),
    ])
    lyr.updateFields()
    features = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                x, y, signal = float(row["x"]), float(row["y"]), int(row["signal"])
                stamp = QDateTime.fromSecsSinceEpoch(int(row["time"]))
            except (KeyError, TypeError, ValueError):
                continue
            feature = QgsFeature(lyr.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(v2q(x, y)))
            feature.setAttributes([signal, row.get("frequency") or "",
                                   row.get("ssid") or "", stamp])
            features.append(feature)
    lyr.dataProvider().addFeatures(features)
    lyr.updateExtents()
    style_wifi_points(lyr, cfg)
    return lyr


def add_to_project(project, run, tif, csv_path, cfg):
    """Add the run's map (and points) on top of the "Wi-Fi maps (Pi)" group,
    replacing layers of the same run loaded before. Returns (raster, points or None)."""
    label = run_label(run)
    root = project.layerTreeRoot()
    group = root.findGroup(group_name()) or root.insertGroup(0, group_name())
    for node in list(group.findLayers()):   # same run loaded before: replace it
        if node.layer() is not None and label in node.layer().name():
            project.removeMapLayer(node.layer().id())

    raster = QgsRasterLayer(tif, tr("Wi-Fi {run}").format(run=label))
    if not raster.isValid():
        raise ValueError("bad_map")
    raster.setCrs(QgsCoordinateReferenceSystem())
    style_wifi_raster(raster, cfg)
    project.addMapLayer(raster, False)
    group.insertLayer(0, raster)

    points = None
    if csv_path and os.path.exists(csv_path):
        points = points_layer(csv_path, tr("Wi-Fi {run} · readings").format(run=label), cfg)
        project.addMapLayer(points, False)
        group.insertLayer(0, points)
    group.setExpanded(True)
    return raster, points
