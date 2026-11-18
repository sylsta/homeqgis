"""Header lines of the panel: robot and Raspberry Pi system information.

Formatting only (no Qt, no network), so it is easy to test. The robot's clock
comes from the HTTP Date header of Valetudo's answers; the Pi's from `date`.
"""

import time

from .i18n import tr

CLOCK_SKEW_S = 120   # beyond this, the device's clock is shown as wrong

# One SSH command for the Pi's block: name, kernel, addresses, clock, uptime.
PI_COMMAND = ("hostname; uname -a; hostname -I 2>/dev/null || echo; date +%s; "
              "cut -d' ' -f1 /proc/uptime")


def pi_test_command(maps_dir):
    """PI_COMMAND, then one line about the Wi-Fi maps folder (relative to home):
    "maps <number of GeoTIFFs>" or "nodir"."""
    import shlex
    folder = shlex.quote(maps_dir or "valetudo_wifi")
    return (f"{PI_COMMAND}; cd; if [ -d {folder} ]; then "
            f"echo maps $(ls {folder}/*.tif 2>/dev/null | wc -l); else echo nodir; fi")


def parse_maps_line(text):
    """Last line of pi_test_command's output -> number of maps, or None (no folder)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    last = lines[-1].split() if lines else []
    if len(last) == 2 and last[0] == "maps" and last[1].isdigit():
        return int(last[1])
    return None


def format_uptime(seconds):
    """3 days 4 h -> '3 d 4 h'; under a day: '5 h 12 min'; under an hour: '7 min'."""
    seconds = int(seconds or 0)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return tr("{days} d {hours} h").format(days=days, hours=hours)
    if hours:
        return tr("{hours} h {minutes} min").format(hours=hours, minutes=minutes)
    return tr("{minutes} min").format(minutes=minutes)


def clock_skew(device_time, received_at):
    """Seconds the device's clock is ahead (+) or behind (-) this computer's."""
    return device_time - received_at


def format_skew(seconds):
    seconds = abs(int(seconds))
    if seconds >= 86400:
        return tr("{days} d").format(days=seconds // 86400)
    if seconds >= 3600:
        return tr("{hours} h").format(hours=seconds // 3600)
    return tr("{minutes} min").format(minutes=max(1, seconds // 60))


def info_line(ip, device_time, received_at, uptime, local_time):
    """(text, clock wrong) for the third header line: IP · date · up N.

    local_time(epoch) formats a time in this computer's time zone."""
    parts, wrong = [], False
    if ip:
        parts.append(ip)
    if device_time is not None:
        text = local_time(device_time)
        skew = clock_skew(device_time, received_at or time.time())
        if abs(skew) > CLOCK_SKEW_S:
            wrong = True
            amount = format_skew(skew)
            text += " (" + (tr("clock {amount} ahead") if skew > 0
                            else tr("clock {amount} behind")).format(amount=amount) + ")"
        parts.append(text)
    if uptime is not None:
        parts.append(tr("up {duration}").format(duration=format_uptime(uptime)))
    return " · ".join(parts), wrong


def parse_pi(text, received_at):
    """Output of PI_COMMAND -> dict(hostname, uname, ip, time, received_at, uptime)."""
    lines = text.splitlines() + [""] * 5
    info = {"hostname": lines[0].strip(), "uname": lines[1].strip(),
            "ip": (lines[2].split() or [""])[0], "received_at": received_at}
    try:
        info["time"] = int(lines[3].strip())
    except ValueError:
        info["time"] = None
    try:
        info["uptime"] = float(lines[4].strip())
    except ValueError:
        info["uptime"] = None
    return info
