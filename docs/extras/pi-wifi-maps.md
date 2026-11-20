# Wi-Fi maps on a Raspberry Pi

With the [recorder on the robot](robot-recorder.md), a Raspberry Pi (or any Linux
machine always on) can fetch each run once the robot is back on its dock and build
its map, without QGIS. The script is `pi/valetudo_wifi_collect.py` in the
repository (not in the plugin zip).

## What it writes

Every few minutes (cron), it asks Valetudo whether the robot is docked. If the
robot's readings have a run it has not processed yet, it fetches them over SSH and
writes, named after the start of the run (the Pi's local time):

- `wifi_YYYY-MM-DD_HH-MM.csv` — the readings;
- `wifi_YYYY-MM-DD_HH-MM.png` — walls, floor, the interpolated signal (red ≤ −80 dBm,
  yellow −67, green ≥ −50) and a dot per reading;
- `wifi_YYYY-MM-DD_HH-MM.tif` — the signal map as a GeoTIFF in the plugin's frame: it
  lines up with the plugin's map layers;
- `latest.png`, `latest.tif` — the newest;
- `wifi_full.csv` / `.png` / `.tif` — the **full map** of all runs, readings averaged
  per cell. `--days N` keeps only the last N days; `--reset` starts again from now.

## Setting it up, once

```sh
sudo apt install python3-numpy python3-gdal      # GDAL only for the GeoTIFF
ssh-keygen -t ed25519                            # if this user has no key yet
ssh-copy-id root@192.168.50.20                   # key login to the robot
mkdir -p ~/valetudo && cp valetudo_wifi_collect.py ~/valetudo/
python3 ~/valetudo/valetudo_wifi_collect.py --robot 192.168.50.20 -v   # try it
crontab -e    # then add:
# */5 * * * * python3 $HOME/valetudo/valetudo_wifi_collect.py --robot 192.168.50.20 -v >> $HOME/valetudo/collect.log 2>&1
```

Output goes to `~/valetudo_wifi` (`--out` to change it; then set the same *Wi-Fi maps
folder* in the Pi's settings). Thresholds, cell size and IDW coefficient have options
(`--help`); `--all` rebuilds every run.

!!! warning "Clocks"
    Run names come from the robot's clock, shown in the Pi's time zone: keep the
    robot synchronised (Valetudo's NTP settings) and set the Pi's time zone
    (`sudo timedatectl set-timezone Europe/Paris`).

## In QGIS

**Load Wi-Fi map from the Pi** (Wi-Fi tab) fetches the newest run, or the full map
when **Full map (all runs)** is ticked, and adds it to a *Wi-Fi maps (Pi)* group: the
map, styled with the plugin's thresholds, and its readings as points. The files are
kept in the QGIS profile folder (`valetudo_wifi_maps/`), so a saved project finds
them again. It needs key-based login from your computer to the Pi. The Pi's
**Log** in the Terminal follows the script's `collect.log`.
