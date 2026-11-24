"""What the history says about the floor.

- dust_age(): each part of the floor by how long since the robot last cleaned it:
  the cleaning segments of each day (history files), widened to the robot's
  cleaning width, newest day first; what no day covered is "not in the last N days".
- trouble_spots(): where the robot had trouble: stuck (it stayed within
  STUCK_RADIUS_CM for at least STUCK_S while cleaning or going somewhere) or in
  error (its state was "error").

Both read the history files (history/store.py); coordinates in cm (core/coords.py).
"""

import datetime
import os

from qgis.core import QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsVectorLayer

from . import changes as map_changes
from ..history.store import day_path

CLEAN_HALF_WIDTH_CM = 16   # the robot cleans a strip about 32 cm wide
MIN_PIECE_CM2 = 400        # smaller pieces of floor are left out (20 x 20 cm)
STUCK_RADIUS_CM = 30
STUCK_S = 45
MOVING = ("cleaning", "go_to", "returning", "mapping", "manual")


def _days(today, days):
    return [today - datetime.timedelta(days=n) for n in range(days)]


def _day_layer(folder, day, name):
    path = day_path(folder, datetime.datetime(day.year, day.month, day.day, 12).timestamp())
    if not os.path.exists(path):
        return None
    layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
    return layer if layer.isValid() else None


def _cleaned(folder, day):
    """The floor cleaned that day: its cleaning segments, widened (or empty)."""
    layer = _day_layer(folder, day, "segments")
    if layer is None:
        return QgsGeometry()
    request = QgsFeatureRequest().setFilterExpression("\"activity\" = 'cleaning'")
    lines = [QgsGeometry(f.geometry()) for f in layer.getFeatures(request)
             if f.hasGeometry() and not f.geometry().isEmpty()]
    if not lines:
        return QgsGeometry()
    return QgsGeometry.collectGeometry(lines).buffer(CLEAN_HALF_WIDTH_CM, 3)


def dust_age(folder, map_features, days=30, today=None):
    """[(polygon, {"days", "last_cleaned"})]: days 0 = today; None = not in the window."""
    today = today or datetime.date.today()
    floor, _walls = map_changes.surfaces(map_features)
    if floor.isEmpty():
        return []
    covered = QgsGeometry()
    found = []
    for n, day in enumerate(_days(today, days)):
        area = _cleaned(folder, day)
        if area.isEmpty():
            continue
        area = area.intersection(floor)
        new = area if covered.isEmpty() else area.difference(covered)
        for part in map_changes.parts(new, MIN_PIECE_CM2):
            found.append((part, {"days": n, "last_cleaned": day.isoformat()}))
        covered = area if covered.isEmpty() else QgsGeometry.unaryUnion([covered, area])
    rest = floor if covered.isEmpty() else floor.difference(covered)
    for part in map_changes.parts(rest, MIN_PIECE_CM2):
        found.append((part, {"days": None, "last_cleaned": None}))
    return found


def _points(folder, day):
    """The day's readings: [(time (s), x, y, activity, state, outing)], in time order."""
    layer = _day_layer(folder, day, "points")
    if layer is None:
        return []
    rows = []
    for f in layer.getFeatures():
        if not f.hasGeometry():
            continue
        when = f["time"]
        if hasattr(when, "toSecsSinceEpoch"):
            when = when.toSecsSinceEpoch()
        if not isinstance(when, (int, float)):
            continue
        p = f.geometry().asPoint()
        rows.append((when, p.x(), p.y(), f["activity"], f["state"], f["outing"]))
    return sorted(rows)


def find_stuck(rows):
    """[(x, y, start, duration_s, outing)]: the robot stayed within STUCK_RADIUS_CM for at
    least STUCK_S while moving about (rows as _points())."""
    spots, i = [], 0
    while i < len(rows):
        t0, x0, y0, activity, _state, outing = rows[i]
        if activity not in MOVING:
            i += 1
            continue
        j = i
        while (j + 1 < len(rows) and rows[j + 1][5] == outing
               and (rows[j + 1][1] - x0) ** 2 + (rows[j + 1][2] - y0) ** 2
               <= STUCK_RADIUS_CM ** 2):
            j += 1
        if rows[j][0] - t0 >= STUCK_S:
            xs, ys = [r[1] for r in rows[i:j + 1]], [r[2] for r in rows[i:j + 1]]
            spots.append((sum(xs) / len(xs), sum(ys) / len(ys), t0, rows[j][0] - t0, outing))
            i = j + 1
        else:
            i += 1
    return spots


def find_errors(rows):
    """[(x, y, time, outing)]: where the robot went into error (first reading of each)."""
    errors, before = [], None
    for when, x, y, _activity, state, outing in rows:
        if state == "error" and before != "error":
            errors.append((x, y, when, outing))
        before = state
    return errors


def trouble_spots(folder, days=30, today=None):
    """[(point, {"kind", "time", "duration_s", "outing"})], newest days first."""
    today = today or datetime.date.today()
    found = []
    for day in _days(today, days):
        rows = _points(folder, day)
        for x, y, start, duration, outing in find_stuck(rows):
            found.append((QgsGeometry.fromPointXY(QgsPointXY(x, y)),
                          {"kind": "stuck", "time": _stamp(start),
                           "duration_s": int(duration), "outing": outing}))
        for x, y, when, outing in find_errors(rows):
            found.append((QgsGeometry.fromPointXY(QgsPointXY(x, y)),
                          {"kind": "error", "time": _stamp(when), "duration_s": None,
                           "outing": outing}))
    return found


def _stamp(seconds):
    return datetime.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
