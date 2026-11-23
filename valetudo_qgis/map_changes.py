"""What the map tells beyond the robot: how it changed, and its walls as lines.

- Snapshots: the first map seen each day is kept in map/versions/robot_map_<date>.gpkg
  (its "rooms" layer: floor, walls and rooms as Valetudo's pixels).
- compare(): the current map against a snapshot. Walls that appeared or went away
  (furniture moved, a door closed or opened), floor that can now be reached or no
  longer can. A shift of a pixel or so (the map is redrawn at each run) is not a
  change: each side is compared with the other widened by TOLERANCE_CM, and pieces
  smaller than MIN_*_CM2 are dropped.
- wall_lines(): the outline of the floor, simplified: the walls as seen from inside
  the rooms, as lines (for plans and measurements).

Map coordinates are in cm (see coords.v2q).
"""

import datetime
import glob
import os
import re

from qgis.core import Qgis, QgsGeometry

VERSIONS_FOLDER = "versions"
SNAPSHOT_PREFIX = "robot_map_"
SNAPSHOT_LAYER = "rooms"
TOLERANCE_CM = 7.5        # 1.5 pixels of 5 cm: jitter between two drawings of the map
MIN_WALL_CM2 = 100        # 4 pixels: smaller wall pieces are noise
MIN_FLOOR_CM2 = 500       # 0.05 m²
SIMPLIFY_CM = 5           # wall lines: straightened within one pixel
MIN_LINE_CM = 50          # wall lines: shorter outlines (a chair leg…) are dropped

FLOOR_TYPES = ("floor", "segment")
WALL_TYPES = ("wall",)
CHANGES = ("wall_added", "wall_removed", "floor_added", "floor_removed")


# -- snapshots ---------------------------------------------------------------------

def snapshot_path(map_folder, day=None):
    day = day or datetime.date.today()
    return os.path.join(map_folder, VERSIONS_FOLDER, f"{SNAPSHOT_PREFIX}{day.isoformat()}.gpkg")


def snapshots(map_folder):
    """[(date, path)], newest first."""
    found = []
    pattern = os.path.join(map_folder, VERSIONS_FOLDER, f"{SNAPSHOT_PREFIX}*.gpkg")
    for path in glob.glob(pattern):
        match = re.search(r"(\d{4}-\d{2}-\d{2})\.gpkg$", path)
        if match:
            try:
                found.append((datetime.date.fromisoformat(match.group(1)), path))
            except ValueError:
                pass
    return sorted(found, reverse=True)


# -- geometry ---------------------------------------------------------------------

def _union(geometries):
    geometries = [g for g in geometries if g is not None and not g.isEmpty()]
    if not geometries:
        return QgsGeometry()
    union = QgsGeometry.unaryUnion(geometries)
    return union.makeValid() if not union.isGeosValid() else union


def surfaces(features):
    """(floor, walls) of a map's pixel layers: features with "type" and geometry."""
    floor, walls = [], []
    for feature in features:
        kind = feature["type"]
        if kind in FLOOR_TYPES:
            floor.append(QgsGeometry(feature.geometry()))
        elif kind in WALL_TYPES:
            walls.append(QgsGeometry(feature.geometry()))
    return _union(floor), _union(walls)


def _parts(geometry, min_area):
    """The polygons of a geometry, at least min_area each."""
    if geometry is None or geometry.isEmpty():
        return []
    parts = geometry.asGeometryCollection() if geometry.isMultipart() else [geometry]
    return [p for p in parts
            if p.type() == Qgis.GeometryType.Polygon and p.area() >= min_area]


def _gained(now, before, min_area):
    """What now has that before (widened by the tolerance) has not."""
    if now.isEmpty():
        return []
    if before.isEmpty():
        return _parts(now, min_area)
    return _parts(now.difference(before.buffer(TOLERANCE_CM, 4)), min_area)


def compare(current, earlier):
    """current, earlier: features of two maps. Returns [(geometry, {"change", "area_m2"})]."""
    floor_now, walls_now = surfaces(current)
    floor_then, walls_then = surfaces(earlier)
    found = []
    for change, now, before, min_area in (
            ("wall_added", walls_now, walls_then, MIN_WALL_CM2),
            ("wall_removed", walls_then, walls_now, MIN_WALL_CM2),
            ("floor_added", floor_now, floor_then, MIN_FLOOR_CM2),
            ("floor_removed", floor_then, floor_now, MIN_FLOOR_CM2)):
        for part in _gained(now, before, min_area):
            found.append((part, {"change": change, "area_m2": round(part.area() / 10000, 3)}))
    return found


def wall_lines(features):
    """The outline of the floor (outer edge and holes), simplified: [(line, {"length_m"})]."""
    floor, _walls = surfaces(features)
    if floor.isEmpty():
        return []
    lines = []
    for part in _parts(floor, 0):
        for ring in part.asPolygon():
            line = QgsGeometry.fromPolylineXY(ring).simplify(SIMPLIFY_CM)
            if line.length() >= MIN_LINE_CM:
                lines.append((line, {"length_m": round(line.length() / 100, 2)}))
    return lines
