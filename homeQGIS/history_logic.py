"""Robot history: outings, segments and points, from successive robot readings.

Plain Python (no QGIS), so that it can be tested on its own. The recorder
(history_recorder.py) feeds readings in; the store (history_store.py) writes
what comes out to one GeoPackage per day.

    outing   from leaving the dock to coming back (dock periods are not recorded)
    segment  a continuous stretch with one activity (cleaning, go_to, returning…)
    point    a reading: time, position, activity, state, battery, Wi-Fi signal

No user-facing text: activities, job types and results are keys.
"""

import hashlib
import math
import time
from datetime import datetime, timedelta, timezone

# activity keys, from Valetudo's status (state, flag)
ACTIVITIES = ("cleaning", "go_to", "returning", "manual", "mapping", "other")
JOB_TYPES = ("vacuum", "mop", "both")
RESULTS = ("finished", "error", "stopped")

MIN_STEP_CM = 5            # a point when the robot moved at least this much…
KEEPALIVE_S = 30           # …or this long after the previous one
IDLE_END_S = 30 * 60       # idle (or in error) away from the dock this long: the outing ends
MIN_OUTING_M = 0.2         # an outing without cleaning that moved less is not kept
SCHEDULE_TOLERANCE_S = 120  # an outing starting this close to a timer is "scheduled"
PLUGIN_START_TOLERANCE_S = 120   # …unless the plugin itself started it this recently


def classify(state, flag):
    """Valetudo status -> (activity, detail). detail: for cleaning, what is cleaned
    (whole home, rooms, zone, spot); "" otherwise. None for the dock and unknown."""
    flag = flag or "none"
    if state == "cleaning":
        return "cleaning", {"segment": "rooms", "zone": "zone", "spot": "spot"}.get(
            flag, "whole_home")
    if state == "returning":
        return "returning", ""
    if state == "moving":
        if flag == "target":
            return "go_to", ""
        if flag == "mapping":
            return "mapping", ""
        return "other", ""
    if state == "manual_control":
        return "manual", ""
    return None


def job_type(presets):
    """Operation mode (and fan / water) -> vacuum, mop or both, or "".

    presets: {"operation_mode": "vacuum_and_mop", "fan_speed": "max", "water_grade": "off"}
    as in Valetudo's PresetSelectionStateAttribute values."""
    mode = (presets.get("operation_mode") or "").lower()
    if mode:
        vacuum = "vacuum" in mode
        mop = "mop" in mode
        if vacuum and mop:
            return "both"
        if vacuum:
            return "vacuum"
        if mop:
            return "mop"
    fan, water = (presets.get("fan_speed") or "").lower(), (presets.get("water_grade") or "").lower()
    if fan == "off" and water and water != "off":
        return "mop"
    if water == "off" and fan and fan != "off":
        return "vacuum"
    if fan and water:
        return "both"
    return ""


def is_scheduled(start, timers, plugin_started_at=None):
    """True if an outing starting at `start` (Unix time) matches an enabled Valetudo
    timer (dow 0 = Sunday, hour and minute in UTC), and the plugin did not start it."""
    if plugin_started_at is not None and abs(start - plugin_started_at) <= PLUGIN_START_TOLERANCE_S:
        return False
    moment = datetime.fromtimestamp(start, tz=timezone.utc)
    for timer in timers or []:
        if not timer.get("enabled", True):
            continue
        for day_offset in (-1, 0, 1):   # a timer just before or after midnight
            day = moment + timedelta(days=day_offset)
            if (day.weekday() + 1) % 7 not in (timer.get("dow") or []):
                continue
            planned = day.replace(hour=int(timer.get("hour", 0)), minute=int(timer.get("minute", 0)),
                                  second=0, microsecond=0)
            if abs((moment - planned).total_seconds()) <= SCHEDULE_TOLERANCE_S:
                return True
    return False


def map_fingerprint(map_json):
    """Short id of the map's rooms: changes when the robot builds a new map."""
    rooms = sorted((str(meta.get("segmentId")), str(meta.get("name") or ""))
                   for layer in (map_json or {}).get("layers", [])
                   if layer.get("type") == "segment"
                   for meta in [layer.get("metaData") or {}])
    return hashlib.sha1(repr(rooms).encode()).hexdigest()[:12] if rooms else ""


def active_rooms(map_json):
    """Names (or ids) of the rooms being cleaned now (the map marks them active)."""
    names = []
    for layer in (map_json or {}).get("layers", []):
        meta = layer.get("metaData") or {}
        if layer.get("type") == "segment" and meta.get("active"):
            names.append(str(meta.get("name") or meta.get("segmentId")))
    return names


def _distance_m(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1]) / 100.0   # positions in cm


class OutingTracker:
    """Turns readings into points, segments and outings.

    update() takes each reading; pop_points(), pop_segments() and pop_outings()
    hand over what is ready to be written. Positions are (x, y) in cm, in the
    frame of the map layers."""

    def __init__(self):
        self.outing = None       # dict of the outing in progress
        self.segment = None      # dict of the segment in progress
        self._points, self._segments, self._outings = [], [], []
        self._last_point = None
        self._override = None    # activity announced by the plugin (e.g. its Go to)
        self.plugin_started_at = None
        self.timers = []

    # -- what the plugin tells -----------------------------------------------------

    def expect(self, activity, now=None):
        """The plugin sends a command: its activity wins over what the robot's status
        says (e.g. a Go to emulated by a zone cleaning), until the robot is back."""
        self._override = activity
        if activity == "cleaning":
            self.plugin_started_at = now if now is not None else time.time()

    # -- readings ------------------------------------------------------------------

    def update(self, t, state, flag=None, pos=None, battery=None, wifi=None, job="",
               rooms=(), map_id=""):
        """One reading. Returns True while an outing is in progress."""
        if state is None:
            return self.outing is not None
        if state == "docked":
            if self.outing is not None:
                self._end(t, "error" if self.outing["had_error"] else "finished")
            self._override = None
            return False
        classified = classify(state, flag)
        if self.outing is None:
            if classified is None and state not in ("paused", "idle", "error"):
                return False
            self._start(t, map_id)
        outing = self.outing
        if state == "error":
            outing["had_error"] = True
        if classified is not None:
            outing["still_since"] = None
            activity, detail = classified
            if self._override and activity in ("cleaning", "other"):
                activity, detail = self._override, ("" if self._override != "cleaning" else detail)
            if activity == "returning":
                self._override = None
        elif state in ("idle", "error"):
            outing["still_since"] = outing["still_since"] or t
            if t - outing["still_since"] >= IDLE_END_S:
                self._end(t, "error" if outing["had_error"] else "stopped")
                return False
            activity, detail = (self.segment or {}).get("activity"), (self.segment or {}).get("detail", "")
        else:   # paused: same activity as before
            activity, detail = (self.segment or {}).get("activity"), (self.segment or {}).get("detail", "")
        if activity is None:
            activity, detail = "other", ""
        job = job if activity == "cleaning" else ""
        for room in rooms:
            if room not in outing["rooms"]:
                outing["rooms"].append(room)
        key = (activity, detail, job)
        if self.segment is None or self.segment["key"] != key:
            self._close_segment(t)
            self._open_segment(t, key)
        if pos is not None:
            self._add_point(t, pos, state, battery, wifi)
        return True

    def finish(self, t):
        """QGIS closes or the robot goes away: close what is open as "stopped"."""
        if self.outing is not None:
            self._end(t, "error" if self.outing["had_error"] else "stopped")

    # -- results -------------------------------------------------------------------

    def pop_points(self):
        out, self._points = self._points, []
        return out

    def pop_segments(self):
        out, self._segments = self._segments, []
        return out

    def pop_outings(self):
        out, self._outings = self._outings, []
        return out

    # -- inside --------------------------------------------------------------------

    def _start(self, t, map_id):
        self.outing = {"outing": datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S"),
                       "start": t, "end": None, "path": [], "activities": [], "job_type": "",
                       "times": [], "spans": [],   # for refine_segments(), not written
                       "rooms": [], "had_error": False, "still_since": None,
                       "scheduled": is_scheduled(t, self.timers, self.plugin_started_at),
                       "map_id": map_id, "area_m2": None}
        self.segment = None
        self._last_point = None

    def _open_segment(self, t, key):
        activity, detail, job = key
        start_path = [self._last_point["pos"]] if self._last_point else []
        self.segment = {"key": key, "outing": self.outing["outing"], "activity": activity,
                        "detail": detail, "job_type": job, "start": t, "end": t,
                        "path": list(start_path), "scheduled": self.outing["scheduled"],
                        # its first position in the outing's path (shared with the previous)
                        "first_i": max(0, len(self.outing["path"]) - len(start_path))}
        if activity not in self.outing["activities"]:
            self.outing["activities"].append(activity)
        if job and not self.outing["job_type"]:
            self.outing["job_type"] = job

    def _close_segment(self, t):
        segment, self.segment = self.segment, None
        if segment is None:
            return
        segment["end"] = t
        path = segment.pop("path")
        segment.pop("key")
        segment["last_i"] = segment["first_i"] + len(path) - 1
        if len(path) >= 2:
            self.outing["spans"].append(segment)
            segment["geometry"] = path
            segment["duration_s"] = int(round(segment["end"] - segment["start"]))
            segment["distance_m"] = round(sum(_distance_m(a, b) for a, b in zip(path, path[1:])), 2)
            self._segments.append(segment)

    def _add_point(self, t, pos, state, battery, wifi):
        last = self._last_point
        segment = self.segment
        moved = last is None or _distance_m(last["pos"], pos) * 100 >= MIN_STEP_CM
        changed = last is None or last["key"] != segment["key"] or last["state"] != state
        if not (moved or changed or t - last["time"] >= KEEPALIVE_S):
            return
        point = {"time": t, "pos": pos, "activity": segment["activity"], "detail": segment["detail"],
                 "job_type": segment["job_type"], "state": state, "battery": battery,
                 "wifi_dbm": wifi, "outing": self.outing["outing"], "source": "live",
                 "key": segment["key"]}
        self._last_point = point
        if moved or not segment["path"]:
            segment["path"].append(pos)
            self.outing["path"].append(pos)
            self.outing["times"].append(t)
        out = dict(point)
        out.pop("key")
        self._points.append(out)

    def _end(self, t, result):
        self._close_segment(t)
        outing, self.outing = self.outing, None
        self._override = None
        path = outing.pop("path")
        outing["samples"] = path   # the readings' positions, for refine_segments()
        distance = round(sum(_distance_m(a, b) for a, b in zip(path, path[1:])), 2)
        outing.pop("still_since")
        had_error = outing.pop("had_error")
        if distance < MIN_OUTING_M and "cleaning" not in outing["activities"]:
            # It hardly moved (e.g. undocked for a moment): keep its points out too
            self._points = [p for p in self._points if p["outing"] != outing["outing"]]
            self._segments = [s for s in self._segments if s["outing"] != outing["outing"]]
            return
        outing.update(end=t, duration_s=int(round(t - outing["start"])), distance_m=distance,
                      result="error" if had_error else result,
                      geometry=path if len(path) >= 2 else None)
        self._outings.append(outing)


# -- browsing (History tab) -----------------------------------------------------------

def week_days(day):
    """The seven dates (Monday first) of the ISO week of a datetime.date."""
    monday = day - timedelta(days=day.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def month_days(day):
    """Every date of the month of a datetime.date."""
    first = day.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return [first + timedelta(days=i) for i in range((following - first).days)]


def year_days(day):
    """Every date of the year of a datetime.date."""
    first = day.replace(month=1, day=1)
    return [first + timedelta(days=i)
            for i in range((first.replace(year=first.year + 1) - first).days)]


def period_days(day, period):
    """The dates of the "day", "week", "month" or "year" around a datetime.date."""
    return {"week": week_days, "month": month_days, "year": year_days}.get(
        period, lambda d: [d])(day)


def week_key(day):
    """(ISO year, ISO week number) of a datetime.date."""
    year, week, _ = day.isocalendar()
    return year, week


def summarize(outings):
    """Totals of outing records (dicts with duration_s, distance_m, area_m2)."""
    return {"count": len(outings),
            "duration_s": sum(o.get("duration_s") or 0 for o in outings),
            "distance_m": round(sum(o.get("distance_m") or 0 for o in outings), 1),
            "area_m2": round(sum(o.get("area_m2") or 0 for o in outings), 1)}


def format_duration(seconds):
    """'45 s', '12 min', '1 h 05'."""
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds} s"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


# -- other sources: the Valetudo path, the recorder on the robot ---------------------

MAX_SPEED_M_S = 0.6          # the robot cannot go further than this along its path…
SLACK_M = 1.5                # …plus this, between two readings
ALIGN_TOLERANCE_M = 0.5      # readings further than this from the path, on average: no match


def align_to_path(samples, times, path):
    """Index in path (a line of many vertices) of each sample (a position read every
    few seconds, at times), going forward only: each sample matches the nearest
    vertex within the distance the robot can have covered since the previous one.
    None when the samples do not follow the path (another job, another map)."""
    if not samples or len(path) < 2:
        return None
    lengths = [0.0]   # cumulative length along the path, in m
    for a, b in zip(path, path[1:]):
        lengths.append(lengths[-1] + _distance_m(a, b))
    indexes, total, start = [], 0.0, 0
    for k, sample in enumerate(samples):
        if k == 0:   # the first one anywhere (the recording may start late)
            candidates = range(len(path))
        else:
            reach = lengths[start] + MAX_SPEED_M_S * max(0.0, times[k] - times[k - 1]) + SLACK_M
            end = start
            while end + 1 < len(path) and lengths[end + 1] <= reach:
                end += 1
            candidates = range(start, end + 1)
        best = min(candidates, key=lambda i: _distance_m(path[i], sample))
        total += _distance_m(path[best], sample)
        indexes.append(best)
        start = best
    return indexes if total / len(samples) <= ALIGN_TOLERANCE_M else None


def refine_segments(outing, path):
    """Give the outing's segments (outing["spans"]) the precise line of Valetudo's
    path between their first and last readings. Returns the segments changed."""
    indexes = align_to_path(outing.get("samples") or [], outing.get("times") or [], path)
    if indexes is None:
        return []
    changed = []
    for segment in outing.get("spans") or []:
        a, b = segment.get("first_i"), segment.get("last_i")
        if a is None or b is None or b >= len(indexes):
            continue
        line = path[indexes[a]:indexes[b] + 1]
        if len(line) >= 2:
            segment["geometry"] = line
            segment["distance_m"] = round(path_length_m(line), 2)
            changed.append(segment)
    return changed


def rooms_on_path(map_json, path, min_m=3.0, min_share=0.05):
    """Names of the rooms a path (Valetudo coordinates) spent at least min_m and
    min_share of its length in, in the order it reached them: the rooms cleaned
    when Valetudo marks none (whole-home cleaning)."""
    map_json = map_json or {}
    size = map_json.get("pixelSize", 5)
    rows = {}   # pixel row -> [(x from, x to, name)]
    for layer in map_json.get("layers", []):
        if layer.get("type") != "segment":
            continue
        meta = layer.get("metaData") or {}
        name = str(meta.get("name") or meta.get("segmentId"))
        cp = layer.get("compressedPixels")
        runs = ([(cp[i], cp[i + 1], cp[i + 2]) for i in range(0, len(cp) - 2, 3)] if cp is not None
                else [(x, y, 1) for x, y in zip(*[iter(layer.get("pixels") or [])] * 2)])
        for x, y, n in runs:
            rows.setdefault(y, []).append((x, x + n, name))
    if not rows or len(path) < 2:
        return []
    metres, order, total = {}, [], 0.0
    for a, b in zip(path, path[1:]):
        step = _distance_m(a, b)
        total += step
        px, py = int((a[0] + b[0]) / 2 // size), int((a[1] + b[1]) / 2 // size)
        name = next((n for x0, x1, n in rows.get(py, ()) if x0 <= px < x1), None)
        if name is not None:
            if name not in metres:
                order.append(name)
            metres[name] = metres.get(name, 0.0) + step
    return [n for n in order if metres[n] >= max(min_m, min_share * total)]


ROBOT_RUN_GAP_S = 5 * 60     # robot readings further apart than this: separate outings
OVERLAP_MARGIN_S = 60        # a robot run this close to a recorded outing is the same one
RECENT_S = 2 * 60            # a robot run that ended this recently may still be going on
CLOCK_TOLERANCE_S = 3        # robot clock difference ignored below this (SSH delay)
PATH_LONGER = 1.2            # the Valetudo path replaces a live line this much shorter


def map_path(map_json):
    """The robot's path of its current or last job ("path" entity of the map), as
    [(x, y), …] in Valetudo coordinates; empty if none."""
    pairs = []
    for entity in (map_json or {}).get("entities", []):
        if entity.get("type") == "path":
            points = entity.get("points") or []
            pairs += [(points[i], points[i + 1]) for i in range(0, len(points) - 1, 2)]
    return pairs


def path_length_m(path):
    return sum(_distance_m(a, b) for a, b in zip(path, path[1:]))


def clock_offset(local_now, robot_now):
    """Seconds to add to the robot's times (0 when its clock is close enough)."""
    if robot_now is None:
        return 0
    offset = local_now - robot_now
    return 0 if abs(offset) < CLOCK_TOLERANCE_S else round(offset)


def _overlaps(start, end, intervals):
    return any(start <= b + OVERLAP_MARGIN_S and end >= a - OVERLAP_MARGIN_S
               for a, b in intervals)


def robot_runs(rows, offset_s=0, recorded=(), now=None, timers=(), convert=None):
    """Outings from the readings of the recorder on the robot (robot_survey.parse_rows:
    time, x, y, signal, state), for the times QGIS was not recording.

    Readings are grouped into runs (gap over ROBOT_RUN_GAP_S between two); a run that
    overlaps a recorded outing (recorded: [(start, end)]) or ended less than RECENT_S
    before now is skipped. Times are corrected by offset_s (see clock_offset);
    convert(x, y) -> (x, y) turns the robot's coordinates into the layers' frame.
    Returns (points, segments, outings, skipped), all marked source "robot"."""
    convert = convert or (lambda x, y: (x, y))
    now = time.time() if now is None else now
    rows = sorted(rows, key=lambda r: r["time"])
    runs, run = [], []
    for row in rows:
        if run and row["time"] - run[-1]["time"] > ROBOT_RUN_GAP_S:
            runs.append(run)
            run = []
        run.append(row)
    if run:
        runs.append(run)
    points, segments, outings, skipped = [], [], [], 0
    for run in runs:
        start, end = run[0]["time"] + offset_s, run[-1]["time"] + offset_s
        if _overlaps(start, end, recorded) or now - end < RECENT_S:
            skipped += 1
            continue
        tracker = OutingTracker()
        tracker.timers = list(timers)
        for row in run:
            tracker.update(row["time"] + offset_s, row.get("state") or "moving", None,
                           convert(row["x"], row["y"]), None, row.get("signal"))
        tracker.update(end, "docked")   # the run is over (back on its dock or paused)
        run_points, run_segments = tracker.pop_points(), tracker.pop_segments()
        run_outings = tracker.pop_outings()
        for record in run_points + run_segments + run_outings:
            record["source"] = "robot"
        for outing in run_outings:
            outing["result"] = ""   # not known: the recorder only sees it move
        points += run_points
        segments += run_segments
        outings += run_outings
    return points, segments, outings, skipped
