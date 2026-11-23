"""Home Assistant's history, for the Home section's graphs (pure Python, no Qt).

GET /api/history/period/<start>?filter_entity_id=a,b&end_time=…&minimal_response
&no_attributes returns one list per entity: its first state in full
({entity_id, state, last_changed}), the next ones minimal ({state,
last_changed}). Home Assistant keeps 10 days by default.

    parse(answer)            -> {entity_id: [(time, state)]}  (Unix times)
    numeric(points)          -> [(time, value)]  (unavailable states left out)
    periods(points, start, end, on=("on",)) -> [(from, to)] while "on"
    stats(series, start, end) -> min, max, time-weighted mean, last
    battery_days_left(series) -> days until 0 % (least squares), or None
    dropouts(points)         -> times the entity became unavailable
"""

from datetime import datetime, timezone
from urllib.parse import quote

UNAVAILABLE = {"unavailable", "unknown", ""}
DAY = 86400
PERIODS = {"6h": 6 * 3600, "24h": DAY, "7d": 7 * DAY, "10d": 10 * DAY}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def history_path(entity_ids, start, end):
    """The API path (after /api) for the history of entities from start to end."""
    ids = ",".join(entity_ids)
    return (f"/history/period/{quote(iso(start))}?filter_entity_id={quote(ids, safe=',')}"
            f"&end_time={quote(iso(end))}&minimal_response&no_attributes")


def _time(text):
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse(answer):
    out = {}
    for series in answer if isinstance(answer, list) else []:
        if not isinstance(series, list) or not series:
            continue
        entity_id = series[0].get("entity_id") if isinstance(series[0], dict) else None
        if not entity_id:
            continue
        points = []
        for state in series:
            if not isinstance(state, dict):
                continue
            t = _time(state.get("last_changed") or state.get("last_updated"))
            if t is not None:
                points.append((t, str(state.get("state", ""))))
        points.sort()
        out[entity_id] = points
    return out


def numeric(points):
    out = []
    for t, state in points:
        try:
            out.append((t, float(state)))
        except ValueError:
            continue
    return out


def is_numeric(points):
    values = [s for _, s in points if s.lower() not in UNAVAILABLE]
    if not values:
        return False
    return all(_float(v) is not None for v in values)


def _float(text):
    try:
        return float(text)
    except ValueError:
        return None


def periods(points, start, end, on=("on", "open", "playing", "home")):
    """[(from, to)] while the state was one of on, clipped to [start, end]."""
    out, since = [], None
    for t, state in points:
        active = state.lower() in on
        if active and since is None:
            since = max(t, start)
        elif not active and since is not None:
            if t > start:
                out.append((since, min(t, end)))
            since = None
    if since is not None and since < end:
        out.append((since, end))
    return [(a, b) for a, b in out if b > a]


def stats(series, start, end):
    """{"min", "max", "mean" (time-weighted), "last"} of a numeric series over
    [start, end], or None without values in it."""
    inside = [(t, v) for t, v in series if start <= t <= end]
    before = [(t, v) for t, v in series if t < start]
    if before:   # the value at the start of the period
        inside.insert(0, (start, before[-1][1]))
    if not inside:
        return None
    total = weight = 0.0
    for (t, v), nxt in zip(inside, inside[1:] + [(end, None)]):
        span = max(0.0, nxt[0] - t)
        total += v * span
        weight += span
    values = [v for _, v in inside]
    return {"min": min(values), "max": max(values),
            "mean": total / weight if weight else values[-1], "last": values[-1]}


def battery_days_left(series, min_span_days=2):
    """Days until the battery reaches 0 %, from the least-squares slope of its readings
    (None when it is not going down, or over too short a time)."""
    if len(series) < 3 or series[-1][0] - series[0][0] < min_span_days * DAY:
        return None
    n = len(series)
    mean_t = sum(t for t, _ in series) / n
    mean_v = sum(v for _, v in series) / n
    var = sum((t - mean_t) ** 2 for t, _ in series)
    if not var:
        return None
    slope = sum((t - mean_t) * (v - mean_v) for t, v in series) / var   # % per second
    if slope >= -1e-9:
        return None
    last_t, last_v = series[-1]
    level = mean_v + slope * (last_t - mean_t)   # on the fitted line, now
    return max(0.0, level / (-slope) / DAY)


def dropouts(points):
    """How many times the entity became unavailable."""
    count, was_down = 0, False
    for _, state in points:
        down = state.lower() in UNAVAILABLE
        if down and not was_down:
            count += 1
        was_down = down
    return count


def sample(series, start, end, buckets):
    """The series as buckets values (last value in each slice, carried forward;
    None before the first value), for a sparkline."""
    if not series or end <= start:
        return [None] * buckets
    out, index, current = [], 0, None
    width = (end - start) / buckets
    for b in range(buckets):
        limit = start + (b + 1) * width
        while index < len(series) and series[index][0] <= limit:
            current = series[index][1]
            index += 1
        out.append(current)
    return out


def robot_cleanings(outings, area_name):
    """[(start, end)] of the robot's outings that cleaned a room named like the area
    (outing dicts as history_store.read_outings gives them)."""
    name = (area_name or "").strip().lower()
    if not name:
        return []
    out = []
    for outing in outings:
        rooms = [r.strip().lower() for r in str(outing.get("rooms") or "").split(",")]
        if name in rooms and outing.get("start") and outing.get("end"):
            out.append((outing["start"], outing["end"]))
    return out


def csv_rows(histories, names=None, units=None):
    """[[time ISO, entity, name, state, unit]] for a CSV export."""
    names, units = names or {}, units or {}
    rows = []
    for entity_id, points in histories.items():
        for t, state in points:
            rows.append([datetime.fromtimestamp(t).isoformat(timespec="seconds"), entity_id,
                         names.get(entity_id, ""), state, units.get(entity_id, "")])
    rows.sort()
    return rows


def hourly_means(series, start, end, step=3600):
    """[(slice start, mean)] of a numeric series, slice by slice (time-weighted);
    slices without any value yet are left out."""
    out = []
    t = start
    while t < end:
        s = stats(series, t, min(t + step, end))
        if s is not None:
            out.append((t, s["mean"]))
        t += step
    return out
