#!/usr/bin/env python3
"""Collect the robot's Wi-Fi survey runs and build a map of each, on a Raspberry Pi.

Meant to run every few minutes from cron. Each time, it:
1. asks Valetudo for the robot state (HTTP); does nothing unless the robot is
   docked (a run is only complete once the robot is back on its dock);
2. reads the last line of the readings file kept on the robot by the
   plugin's Wi-Fi recorder (SSH); does nothing if that run is already done;
3. otherwise fetches the file, and for each run not yet processed writes,
   named after the time the run started (local time):
     wifi_YYYY-MM-DD_HH-MM.csv   the readings
     wifi_YYYY-MM-DD_HH-MM.png   a picture: walls, floor, signal map, points
     wifi_YYYY-MM-DD_HH-MM.tif   the signal map as a GeoTIFF (needs GDAL),
                                 in the plugin's frame: it lines up with the
                                 plugin's map layers in QGIS
   and points latest.png / latest.tif at the newest ones.

The map is an IDW interpolation, clipped to the robot's floor and rooms, with
the plugin's colours and thresholds (red / yellow / green).

Needs: Python 3, numpy (sudo apt install python3-numpy), and for the GeoTIFF
GDAL (sudo apt install python3-gdal); an SSH key of this user authorised on the
robot (ssh-copy-id root@<robot>). Run with --help for the options.
"""

import argparse
import base64
import csv
import json
import os
import struct
import subprocess
import sys
import time
import urllib.request
import zlib

try:
    import numpy as np
except ImportError:
    sys.exit("numpy is needed: sudo apt install python3-numpy")

DATA_NAME = "valetudo_wifi_survey.csv"
ROBOT_DIRS = ("/data", "/mnt/UDISK", "/mnt/data", "/userdata", "/tmp")
COLOR_BAD, COLOR_FAIR, COLOR_GOOD = (0xD7, 0x19, 0x1C), (0xFD, 0xD8, 0x35), (0x1A, 0x96, 0x41)
FIELDS = ["session", "time", "x", "y", "signal", "state", "ssid", "frequency"]


def log(message, args):
    if args.verbose:
        print(time.strftime("%H:%M:%S"), message)


# -- robot access -------------------------------------------------------------------

def http_json(args, path):
    request = urllib.request.Request(f"http://{args.robot}/api/v2{path}")
    if args.http_auth:
        token = base64.b64encode(args.http_auth.encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=20) as reply:
        return json.load(reply)


def ssh(args, command):
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-p", str(args.ssh_port),
         f"{args.ssh_user}@{args.robot}", command],
        capture_output=True, timeout=120)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"ssh exit code {result.returncode}")
    return result.stdout.decode("utf-8", "replace")


def robot_status(args):
    for attr in http_json(args, "/robot/state/attributes"):
        if attr.get("__class") == "StatusStateAttribute":
            return attr.get("value")
    return None


def find_data_file(args):
    if args.robot_file:
        return args.robot_file
    candidates = " ".join(f"{d}/{DATA_NAME}" for d in ROBOT_DIRS)
    found = ssh(args, f"for f in {candidates}; do [ -f \"$f\" ] && echo \"$f\" && break; done; true")
    return found.strip() or None


def parse_rows(text):
    rows = []
    for line in text.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 5:
            continue
        try:
            row = {"session": int(parts[0]), "time": int(parts[1]), "x": float(parts[2]),
                   "y": float(parts[3]), "signal": int(parts[4])}
        except ValueError:
            continue
        for i, name in enumerate(FIELDS[5:], start=5):
            row[name] = parts[i] if len(parts) > i else ""
        rows.append(row)
    return rows


# -- map of the robot (floor, rooms, walls) -----------------------------------------------

def map_masks(map_json):
    """(floor pixel set, wall pixel set, pixel size in cm) from Valetudo's map."""
    floor, walls = set(), set()
    for layer in map_json.get("layers", []):
        pixels = layer.get("compressedPixels") or []
        target = walls if layer.get("type") == "wall" else floor
        for i in range(0, len(pixels) - 2, 3):
            x, y, count = pixels[i], pixels[i + 1], pixels[i + 2]
            for dx in range(count):
                target.add((x + dx, y))
    return floor, walls, int(map_json.get("pixelSize") or 5)


# -- interpolation ------------------------------------------------------------------

def idw_grid(rows, args, floor, pixel_cm):
    """Signal grid (NaN outside the floor), its origin (cm) and cell size (cm)."""
    xs = np.array([r["x"] for r in rows], dtype=float)
    ys = np.array([r["y"] for r in rows], dtype=float)
    values = np.array([r["signal"] for r in rows], dtype=float)
    cell = float(args.cell)
    if floor:
        fx = [p[0] for p in floor]
        fy = [p[1] for p in floor]
        x0, x1 = min(fx) * pixel_cm, (max(fx) + 1) * pixel_cm
        y0, y1 = min(fy) * pixel_cm, (max(fy) + 1) * pixel_cm
    else:
        margin = 2 * cell
        x0, x1 = xs.min() - margin, xs.max() + margin
        y0, y1 = ys.min() - margin, ys.max() + margin
    width, height = int(np.ceil((x1 - x0) / cell)), int(np.ceil((y1 - y0) / cell))
    cx = x0 + (np.arange(width) + 0.5) * cell
    cy = y0 + (np.arange(height) + 0.5) * cell
    gx, gy = np.meshgrid(cx, cy)
    grid = np.empty((height, width))
    for r in range(height):   # row by row: bounded memory on a Pi
        d2 = (gx[r][:, None] - xs[None, :]) ** 2 + (gy[r][:, None] - ys[None, :]) ** 2
        exact = d2 < 1e-6
        weights = 1.0 / np.maximum(d2, 1e-6) ** (args.power / 2)
        line = (weights * values).sum(axis=1) / weights.sum(axis=1)
        hit = exact.any(axis=1)
        line[hit] = values[exact[hit].argmax(axis=1)]
        grid[r] = line
    if floor:
        px = (gx // pixel_cm).astype(int)
        py = (gy // pixel_cm).astype(int)
        inside = np.vectorize(lambda a, b: (a, b) in floor)(px, py)
        grid[~inside] = np.nan
    return grid, (x0, y0), cell


def colour(signal, args):
    """Plugin's ramp: red -> yellow -> green between the three thresholds."""
    def mix(a, b, t):
        t = min(1.0, max(0.0, t))
        return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    if signal <= args.fair:
        return mix(COLOR_BAD, COLOR_FAIR, (signal - args.bad) / max(1, args.fair - args.bad))
    return mix(COLOR_FAIR, COLOR_GOOD, (signal - args.fair) / max(1, args.good - args.fair))


# -- outputs ------------------------------------------------------------------------

def write_png(path, rgb):
    """rgb: (height, width, 3) uint8 array. Plain zlib, no imaging library needed."""
    height, width, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[r].tobytes() for r in range(height))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def render_png(path, rows, grid, origin, cell, floor, walls, pixel_cm, args):
    """Map pixels scaled up: background, floor, signal (blended), walls, points."""
    scale = args.png_scale
    if floor or walls:
        all_px = floor | walls
        mx0 = min(p[0] for p in all_px)
        my0 = min(p[1] for p in all_px)
        mx1 = max(p[0] for p in all_px) + 1
        my1 = max(p[1] for p in all_px) + 1
    else:
        mx0, my0 = int(origin[0] // pixel_cm), int(origin[1] // pixel_cm)
        mx1 = mx0 + int(grid.shape[1] * cell // pixel_cm)
        my1 = my0 + int(grid.shape[0] * cell // pixel_cm)
    w, h = mx1 - mx0, my1 - my0
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    alpha = args.opacity / 100.0
    for py in range(h):
        for px in range(w):
            pixel = (px + mx0, py + my0)
            if pixel in walls:
                img[py, px] = (40, 40, 40)
                continue
            if floor and pixel not in floor:
                continue
            base = np.array((225, 225, 225))
            cx, cy = (pixel[0] + 0.5) * pixel_cm, (pixel[1] + 0.5) * pixel_cm
            gc, gr = int((cx - origin[0]) // cell), int((cy - origin[1]) // cell)
            if 0 <= gr < grid.shape[0] and 0 <= gc < grid.shape[1] and not np.isnan(grid[gr, gc]):
                base = base * (1 - alpha) + np.array(colour(grid[gr, gc], args)) * alpha
            img[py, px] = base
    img = img.repeat(scale, axis=0).repeat(scale, axis=1)
    for row in rows:   # readings as small dark dots
        px = int((row["x"] / pixel_cm - mx0) * scale)
        py = int((row["y"] / pixel_cm - my0) * scale)
        img[max(0, py - 1):py + 2, max(0, px - 1):px + 2] = (20, 20, 20)
    write_png(path, img)


def write_geotiff(path, grid, origin, cell):
    """Signal grid in the plugin's frame (x, -y), no CRS, like the plugin's layers."""
    try:
        from osgeo import gdal
    except ImportError:
        return False
    gdal.UseExceptions()   # explicit (GDAL warns otherwise); errors become exceptions
    height, width = grid.shape
    ds = gdal.GetDriverByName("GTiff").Create(path, width, height, 1, gdal.GDT_Float32,
                                              ["COMPRESS=DEFLATE"])
    # Row 0 is the top: the smallest Valetudo y, i.e. the largest plugin y (-y).
    ds.SetGeoTransform((origin[0], cell, 0.0, -origin[1], 0.0, -cell))
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(np.where(np.isnan(grid), -9999.0, grid).astype(np.float32))
    band.SetDescription("Wi-Fi signal (dBm)")
    ds.FlushCache()
    ds = None
    return True


def link_latest(out_dir, name, suffix):
    link = os.path.join(out_dir, f"latest{suffix}")
    try:
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(name + suffix, link)
    except OSError:
        pass


# -- main ---------------------------------------------------------------------------

def process_run(rows, map_json, args):
    stamp = time.strftime("%Y-%m-%d_%H-%M", time.localtime(rows[0]["session"]))
    name = f"wifi_{stamp}"
    base = os.path.join(args.out, name)
    with open(base + ".csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    if len(rows) < 3:
        log(f"{name}: {len(rows)} reading(s), too few for a map", args)
        return name
    floor, walls, pixel_cm = map_masks(map_json) if map_json else (set(), set(), 5)
    grid, origin, cell = idw_grid(rows, args, floor, pixel_cm)
    render_png(base + ".png", rows, grid, origin, cell, floor, walls, pixel_cm, args)
    link_latest(args.out, name, ".png")
    try:
        written = write_geotiff(base + ".tif", grid, origin, cell)
    except Exception as exc:   # GDAL error: keep the CSV and PNG of this run
        print(f"{name}: GeoTIFF not written: {exc}", file=sys.stderr)
        written = None
    if written:
        link_latest(args.out, name, ".tif")
    elif written is False:
        log("GDAL not found: no GeoTIFF (sudo apt install python3-gdal)", args)
    log(f"{name}: {len(rows)} readings -> csv, png" + (", tif" if os.path.exists(base + ".tif")
                                                       else ""), args)
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--robot", default="192.168.50.20", help="robot address")
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--http-auth", default="", help="user:password if Valetudo has HTTP auth")
    parser.add_argument("--robot-file", default="", help="readings file on the robot "
                        "(default: found among " + ", ".join(ROBOT_DIRS) + ")")
    parser.add_argument("--out", default=os.path.expanduser("~/valetudo_wifi"),
                        help="output folder")
    parser.add_argument("--cell", type=float, default=10, help="map cell size, cm")
    parser.add_argument("--power", type=float, default=2, help="IDW distance coefficient")
    parser.add_argument("--bad", type=int, default=-80, help="red at or below, dBm")
    parser.add_argument("--fair", type=int, default=-67, help="yellow, dBm")
    parser.add_argument("--good", type=int, default=-50, help="green at or above, dBm")
    parser.add_argument("--opacity", type=int, default=70, help="signal over the floor, %%")
    parser.add_argument("--png-scale", type=int, default=3, help="PNG pixels per map pixel")
    parser.add_argument("--all", action="store_true", help="redo every run, even done ones")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    done_path = os.path.join(args.out, ".done_sessions")
    done = set()
    if os.path.exists(done_path) and not args.all:
        with open(done_path) as f:
            done = {int(line) for line in f if line.strip().isdigit()}

    try:
        status = robot_status(args)
    except Exception as exc:   # robot off, rebooting, out of reach: try again next time
        log(f"robot not reachable: {exc}", args)
        return 0
    if status != "docked" and not args.all:
        log(f"robot {status}: waiting for it to be docked", args)
        return 0

    try:
        path = find_data_file(args)
        if not path:
            log("no readings file on the robot (is the Wi-Fi recorder installed?)", args)
            return 0
        last = parse_rows(ssh(args, f'tail -n 1 "{path}" 2>/dev/null; true'))
        if not last or (last[0]["session"] in done and not args.all):
            log("nothing new", args)
            return 0
        rows = parse_rows(ssh(args, f'cat "{path}"'))
    except Exception as exc:
        print(f"SSH failed: {exc}", file=sys.stderr)
        return 1

    runs = {}
    for row in rows:
        runs.setdefault(row["session"], []).append(row)
    todo = [s for s in sorted(runs) if args.all or s not in done]
    try:
        map_json = http_json(args, "/robot/state/map")
    except Exception as exc:
        log(f"map not available ({exc}): maps not clipped to the floor", args)
        map_json = None
    for session in todo:
        process_run(runs[session], map_json, args)
        done.add(session)
    with open(done_path, "w") as f:
        f.write("".join(f"{s}\n" for s in sorted(done)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
