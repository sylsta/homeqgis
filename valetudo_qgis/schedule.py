"""Valetudo timers <-> what the user sees: local days and time.

Valetudo stores and runs timers in UTC; days are 0 = Sunday … 6 = Saturday.
The plugin shows and edits them in local time with the current UTC offset,
as Valetudo's own interface does: after a daylight-saving change a timer
starts one hour off until it is saved again.

No Qt here (offsets are passed in minutes), so this module is easy to test.
"""

PRE_ACTION_CAPABILITIES = {   # timer pre-action type -> preset capability
    "fan_speed_control": "FanSpeedControlCapability",
    "water_usage_control": "WaterUsageControlCapability",
    "operation_mode_control": "OperationModeControlCapability",
}
MINUTES_PER_DAY = 24 * 60


def _shift(days, hour, minute, delta_minutes):
    total = hour * 60 + minute + delta_minutes
    day_shift, total = divmod(total, MINUTES_PER_DAY)
    return sorted({(d + day_shift) % 7 for d in days}), total // 60, total % 60


def local_to_utc(days, hour, minute, offset_minutes):
    """Local days (0 = Sunday), hour, minute -> UTC ones (offset: local - UTC)."""
    return _shift(days, hour, minute, -offset_minutes)


def utc_to_local(days, hour, minute, offset_minutes):
    return _shift(days, hour, minute, offset_minutes)


def new_timer():
    """Defaults of a new timer: every weekday at 10:00 local, whole home."""
    return {"enabled": True, "label": "", "dow": [1, 2, 3, 4, 5], "hour": 10, "minute": 0,
            "action": {"type": "full_cleanup", "params": {}}, "pre_actions": []}


def build_timer(base, label, local_days, hour, minute, offset_minutes, segment_ids=None,
                iterations=1, custom_order=False, pre_actions=None, enabled=True):
    """The JSON Valetudo expects; base supplies the id when editing."""
    dow, utc_hour, utc_minute = local_to_utc(local_days, hour, minute, offset_minutes)
    if segment_ids:
        action = {"type": "segment_cleanup",
                  "params": {"segment_ids": [str(s) for s in segment_ids],
                             "iterations": max(1, int(iterations)),
                             "custom_order": bool(custom_order)}}
    else:
        action = {"type": "full_cleanup", "params": {}}
    timer = {"enabled": bool(enabled), "label": label.strip()[:24], "dow": dow,
             "hour": utc_hour, "minute": utc_minute, "action": action,
             "pre_actions": [{"type": kind, "params": {"value": value}}
                             for kind, value in (pre_actions or {}).items() if value]}
    if base and base.get("id"):
        timer["id"] = base["id"]
    return timer


def local_schedule(timer, offset_minutes):
    """(local days, hour, minute) of a timer."""
    return utc_to_local(timer.get("dow") or [], int(timer.get("hour", 0)),
                        int(timer.get("minute", 0)), offset_minutes)


def pre_action_values(timer):
    """{pre-action type: value} of a timer."""
    return {p.get("type"): (p.get("params") or {}).get("value")
            for p in timer.get("pre_actions") or [] if isinstance(p, dict)}


def sort_key(timer, offset_minutes):
    days, hour, minute = local_schedule(timer, offset_minutes)
    first = min(((d - 1) % 7 for d in days), default=7)   # Monday first
    return (first, hour, minute, timer.get("label") or "")
