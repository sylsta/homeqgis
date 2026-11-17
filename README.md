# Valetudo for QGIS

A learning project: display and control a [Valetudo](https://valetudo.cloud) robot
vacuum from QGIS. The plugin talks to Valetudo's local REST API (no cloud).

Available in English and French (the UI follows the QGIS interface language).

## Installation

**From a build (recommended):** each push to `main` builds a ready-to-install zip,
with compiled translations, in the *Actions* tab of this repository (artifact
`valetudo_qgis`). Unzip the downloaded artifact once to get `valetudo_qgis.zip`,
then in QGIS: *Plugins > Manage and Install Plugins > Install from ZIP*.

**For development:**

1. In QGIS: *Settings > User Profiles > Open Active Profile Folder*.
2. Go to `python/plugins/` (create it if needed).
3. Copy the `valetudo_qgis` folder of this repository there, or better, symlink it
   so that every `git pull` is picked up directly.
4. Optional, for the French UI: run `scripts/compile_translations.sh`
   (needs Qt's `lrelease`).
5. Restart QGIS and enable "Valetudo" in *Plugins > Manage and Install Plugins > Installed*.

Tip: install the **Plugin Reloader** plugin to reload the code after each change
without restarting QGIS.

## Usage

1. *Settings > Options > Valetudo* (or *Plugins > Valetudo > Settings…*, which opens
   that page): enter the robot address (e.g. `http://192.168.1.23`), click
   **Test connection**, then **OK**. As for every Options page, *Cancel* saves nothing.
2. Open the **Valetudo panel** (the only toolbar button, or *Plugins > Valetudo*).
   The menu and the toolbar stay minimal: everything happens in the panel.

The panel (titled *Connection*), from top to bottom:

```
┌──────────────────────────────────────────────────────┐
│ ▸ (logo) [Cleaning] ▮▮▮▮▯ 82 %  Wi-Fi -55  12 min · 18 m²  ⚠ │ (Pi) ● Online │ (HA) ● Online  [🗺] [⋮] │  status strip
│   (click it: robot, Raspberry Pi and Home Assistant details)       │
├──┬───────────────────────────────────────────────────┤
│🧹│ Clean     rooms tree, cleaning profile, buttons   │
│📅│ Schedule  week view + list                        │
│📶│ Wi-Fi     signal, colours, recordings, Pi maps    │
│📷│ Camera                                            │
│🧰│ Care      consumables, dock station, statistics   │
│⌨ │ Terminal  [Robot | Pi | HA]  [Console | Log]      │
│⚙ │ System    robot and Pi cards, boot log, events    │
├──┴───────────────────────────────────────────────────┤
│ [ Start cleaning all rooms ] [Dock]                  │  big button, at the bottom
└──────────────────────────────────────────────────────┘
```

- **Status strip**, always visible: the state, battery, Wi-Fi signal (coloured with
  the thresholds of the Wi-Fi tab), the job in progress (time and area), a ⚠ when
  something needs you (dock tank empty or full, worn consumable, robot error,
  wrong clock: hover it for the list, click it to open the right tab), the
  Raspberry Pi's status (when one is set: checked over SSH every 30 s), Home
  Assistant's status (checked every minute: *Online*, *No token* when it answers
  but no access token is set, *Offline*; hidden when there is neither a token nor
  an answer; hover it for the server's name and version), *Show on map*
  and the ⋮ menu (Locate, Watch robot boot, Reboot, Settings, Refresh now, Compact
  mode). **Click the ▸ arrow** (or the strip) to show or hide the details, folded
  each time QGIS starts: connection, robot model,
  Valetudo version and Wi-Fi, then the robot's address, its own clock (orange, with
  how far off, when it differs from the computer's by more than 2 minutes) and
  uptime, the state and battery, with *Show on map* and *Refresh now* on the first
  line; with a Raspberry Pi set in the settings, the same for the Pi (read over
  SSH every 30 s while the panel is visible); then Home Assistant: version, home
  name and time zone, its address, its own clock and its uptime (from the *Uptime*
  integration's `sensor.uptime`, if you have it).
- **Big button**, at the bottom of the panel, after the robot's state: *Start
  cleaning all rooms* when docked or idle, *Pause* while it works, *Resume* when
  paused; *Dock* next to it while away from the dock.
- **Side tabs**: icons, their names as tooltips; a tab gets an orange dot when one
  of the problems of the ⚠ belongs to it.
- **Compact mode** (⋮ menu, off by default): only the strip and the big button;
  click the strip to unfold or fold the rest. The panel never folds by itself (when
  QGIS loses the focus or the mouse goes elsewhere).

**Clean** tab
- Rooms are a checkable tree: *All rooms*, then your own **room groups**. Ticking
  a group ticks its rooms (partial when only some are); a room in several groups
  is the same room, ticked everywhere and cleaned once.
- **Cleaning profile**: mode (vacuum only, mop only or both), water usage, fan speed,
  as the robot offers them; applied at once.
- *Clean everything*, *Clean room(s)* (the ticked ones), *Clean a zone…*, *Go to…*,
  and **Passes** (1 to 3) for rooms and zones. *Clean a zone…* and *Go to…* stay
  pressed until you have drawn the zone or clicked the point on the map.
- **Room groups** are defined in `valetudo_room_groups.ini`, in the QGIS profile
  folder (right-click in the tree, or *Edit room groups…* in the settings, opens it):

  ```ini
  # one [Group] per section, one room per line (as named on the robot,
  # case does not matter), or #<id>
  [Water]
  Kitchen
  SdB1

  [Main]
  Chill
  Eat
  ```

  The panel reloads it as soon as it is saved; names the robot does not know are
  shown greyed out ("not found on the robot").
- **Edit rooms**: right-click a room (in the tree, or on the map with *Pick rooms on
  the map*) → *Rename…*, *Join with ▸* another room, or *Split with a line on the
  map…* (click the two ends of the cut line, from wall to wall; right-click or Esc
  cancels). Each edit asks for confirmation; the room list and the map are then
  reloaded. If the robot refuses (e.g. a split line that does not cross the room),
  its own message is shown.
- **Go to…** on robots without Valetudo's go-to (e.g. Eureka J15 Pro Ultra): a 60 cm
  zone clean at that spot, then a pause as soon as the robot is within 50 cm.
  With **Without cleaning** ticked (under the button, on by default),
  the plugin first reads the robot's fan speed, water usage and mode, switches to
  the quietest ones it offers (mode "vacuum" so the mops stay up, water off, fan off
  or lowest), and puts yours back when the trip ends, whatever its end. If the robot
  refuses a change, the trip is cancelled and nothing is left changed. Most robots
  have no "fan off" in Valetudo: they still vacuum gently on the way.

**On the map**
- **Show on map** (in the strip) loads the map, refreshes the robot live and keeps it
  in view (recentring only when it nears the edge). Click again to stop. It is
  turned on by itself when QGIS starts with an empty project and the robot answers
  within a minute (*Settings > Options > Valetudo*, tab *Robot*: "Show the robot on
  the map when QGIS starts with an empty project"); a project with layers is left
  untouched.
- While it is on, a **Valetudo map** toolbar appears: *Pick rooms on the map* (click a
  room to tick or untick it in the Clean tab, right-click it for its menu), *Edit
  no-go zones and walls*, *Send no-go zones and walls to robot…*; and a small
  **status card** (state, battery, job) sits in the map's top right corner, so the
  robot can be watched with the panel closed.

The panel refreshes itself while visible (every 5 s while the robot works, every
30 s otherwise), even when the robot is docked. Sections fold with their arrow
(remembered).

**Camera**: robots that expose a raw H.264 stream over TCP (default
`tcp://<robot>:8555`). Needs **ffmpeg** (found in the `PATH`, or set its path in
the settings). It starts at the robot's next full image (key frame), so the first
image can take a few seconds (the status shows how long); after leaving the tab, the
stream keeps running for a minute so that coming back is instant. The stream
reconnects by itself if it drops, and **Save snapshot** (or Ctrl+Shift+S in the
tab) saves the current image as PNG. **Full screen** shows the video in its own
window (Esc or a double-click closes it).

**No-go zones and virtual walls**: *Edit no-go zones and walls* loads the
robot's restrictions into two editable layers ("no-go zones" polygons, with a
No-go / No-mop type, and "virtual walls" lines), on top of the map. Edit them
with the usual QGIS tools (add, move vertices, snapping, undo); a bar at the top
of the map offers *Send to robot…* (after a confirmation, they replace the
robot's restrictions) and *Discard changes*. Valetudo needs 4 corners per zone and 2 points per wall: other
shapes are converted (bounding rectangle, line ends) and the confirmation says
so.

**Dock station notifications**: once a robot is configured, the plugin checks
the dock every minute in the background (panel open or not) and shows a
persistent warning when the fresh water tank or the detergent is empty, the
waste water tank or the dust bag is full, or a tank is missing; a short message
confirms when it is OK again. Turn it off in the settings.

**Wi-Fi tab**: the signal now, with a graph of the last 10 minutes, and the three
colour thresholds (green, yellow, red from), used by the strip, the graph and the
maps. *Record Wi-Fi survey* (with QGIS open) reads the robot's Wi-Fi
signal at regular intervals and stores it as a point at the robot's position (layer
"Wi-Fi survey", fields `signal` in dBm, `frequency`, `ssid`, `time`). Start a
cleaning, let the robot go everywhere, then click the button again: the points are
interpolated (IDW) into the "Wi-Fi signal (dBm)" raster, clipped to the rooms and
coloured with fixed thresholds (red / yellow / green), so that two surveys can be
compared. Several recordings add to the same layer for a smoother map. *Build Wi-Fi
map* rebuilds it, from the selected points only if some are selected (e.g. one Wi-Fi
band). Every value (reading interval, minimum distance between points, maximum age of
the position, cell size, IDW coefficient, thresholds, opacity, clipping) is in the
settings, tab *Wi-Fi survey*. Check first in the Swagger UI that the robot's
`WifiConfigurationCapability` returns a fresh `signal` at each call: if it is cached,
use a longer reading interval.

**Wi-Fi survey recorded on the robot** (Wi-Fi tab, *Recorder on the robot*, which
says whether it is installed and where), so that QGIS does not have to
stay open: *Record Wi-Fi on the robot…* installs a small shell script on the robot
over SSH (same key-based login and settings as the reboot) and starts it. From then
on, whenever the robot moves (cleaning, returning to its dock, moving, manual
control), the script records its Wi-Fi signal (read from `/proc/net/wireless`, so
always fresh) and its position from Valetudo's map, at the reading interval and
minimum distance of the *Wi-Fi survey* settings; each run is kept apart. Docked or
idle, it only checks the robot state every 10 s. *Import Wi-Fi from the robot*
brings the readings into the "Wi-Fi survey" layer (readings already imported are
skipped) and builds the Wi-Fi map. *Remove Wi-Fi recorder from robot…* stops it and
deletes it with its readings.

- The script and its readings go to the first writable folder among `/data`,
  `/mnt/UDISK`, `/mnt/data`, `/userdata` and `/tmp` (the message after the install
  says which). In `/tmp` they are lost at each robot reboot.
- The robot does not start it at boot by itself: the plugin starts it again each
  time it connects to the robot. To have it start with the robot, add this line to
  the robot's own boot script, the one that starts Valetudo (with the folder
  given at install):
  `sh /data/valetudo_wifi_survey.sh /data/valetudo_wifi_survey.csv 2 20 &`
- It needs `wget` or `curl` on the robot; the install message says if something
  is missing. It reads Valetudo locally without a password: it does not work if
  Valetudo's HTTP authentication is turned on.
- The file is limited to the last 50,000 readings (about 2.5 MB).

**Reboot robot (SSH)…** (Valetudo menu and status panel): Valetudo deliberately
has no reboot API, so the plugin runs `ssh <user>@<robot> reboot` after a
confirmation. It needs an SSH client and key-based login to the robot
(`ssh-copy-id root@<robot>`); no password is ever stored or asked for. SSH user
and port are in the settings (`root`, 22 by default).

**Terminal** tab, *Log* (Robot): follows Valetudo's log file on the robot, `/tmp/valetudo.log`, as
`ssh root@<robot> 'tail -f /tmp/valetudo.log'` would (last 200 lines, then new
ones as they come; errors in red, warnings in orange). It only runs while the tab
is shown and the panel is visible, uses the same key-based SSH login and settings
as the reboot, and reconnects by itself 10 s after the link drops (e.g. while the
robot reboots). *Scroll to new lines* keeps the newest line in view; untick it to
read older lines in peace. *Clear* empties the view (not the file).

**Schedule** tab: Valetudo's own timers, run by the robot itself, even when QGIS
is closed. A **week view** (Monday to Sunday, 6:00 to midnight) shows each scheduled
cleaning as a block (grey when off): click a block to select it, double-click it to
edit it, double-click an empty slot to create one there, or **drag a room group** (or
a room) from the Clean tab and drop it on a day and time to schedule it. Below, one
line per cleaning (name, days, time, what); tick it to turn it on or off,
double-click or *Edit…* to change it, *Run now* to start it at once. **Tonight…**
cleans the ticked rooms (or the whole home) once, at the time you choose today (or
tomorrow if already past): it is a timer named "Once dd/MM HH:mm" that the plugin
deletes an hour after its start, the next time it connects (if QGIS is not opened
within a week, it would run again the same day the next week).
The editor sets the name, the days and time, *Whole home* or *Selected rooms*
(the same rooms tree as the Clean group, with your room groups; optionally in the
order ticked, and the number of passes), and the fan speed, water usage and mode
to apply first (only those the robot supports; *Unchanged* leaves them as they
are). Changes are saved on the robot at once, so they also appear in Valetudo's
own interface. Times are shown in local time; Valetudo stores them in UTC, so
after a change to or from summer time a cleaning starts one hour off until it is
saved again. The robot's clock must be right (see Valetudo's NTP settings).

**Wi-Fi maps built on a Raspberry Pi** (`pi/valetudo_wifi_collect.py`, not part of the
plugin zip): with the Wi-Fi recorder installed on the robot, a Pi (or any Linux
machine always on) fetches each run once the robot is back on its dock and builds
its map, without QGIS. Every few minutes (cron), the script asks Valetudo whether
the robot is docked; if the robot's readings file has a run it has not processed
yet, it fetches the file over SSH and writes, named after the time the run
started (local time of the Pi):

- `wifi_YYYY-MM-DD_HH-MM.csv`: the readings of that run;
- `wifi_YYYY-MM-DD_HH-MM.png`: walls, floor, the interpolated signal (IDW,
  clipped to the floor; red ≤ −80 dBm, yellow −67, green ≥ −50, as in the plugin)
  and a dot per reading;
- `wifi_YYYY-MM-DD_HH-MM.tif`: the signal map as a GeoTIFF in the plugin's frame
  (no CRS): drop it in QGIS and it lines up with the plugin's map layers;
- `latest.png` and `latest.tif`, links to the newest;
- `wifi_full.csv` / `.png` / `.tif`: the **full map**, rebuilt after each new run
  from all runs: the readings are first averaged per map cell, so that places the
  robot visits often do not outweigh the others, and areas missed by one run are
  filled by the others. `--days N` keeps only the last N days in it (Wi-Fi changes
  when the router or the furniture move); `--reset` starts it again from now.

Set up on the Pi, once:

```sh
sudo apt install python3-numpy python3-gdal      # GDAL only for the GeoTIFF
ssh-keygen -t ed25519                            # if this user has no key yet
ssh-copy-id root@192.168.50.20                   # key login to the robot
mkdir -p ~/valetudo && cp valetudo_wifi_collect.py ~/valetudo/
python3 ~/valetudo/valetudo_wifi_collect.py --robot 192.168.50.20 -v   # try it
crontab -e    # then add:
# */5 * * * * python3 $HOME/valetudo/valetudo_wifi_collect.py --robot 192.168.50.20 -v >> $HOME/valetudo/collect.log 2>&1
```

In QGIS, *Load Wi-Fi map from the Pi* (Advanced tab) fetches over SSH the newest
run, or the full map when **Full map (all runs)** (just under the button) is ticked, (the Pi as set in *Settings > Options > Valetudo*, tab *Raspberry Pi*) and
adds it to a "Wi-Fi maps (Pi)" group: the map, styled with the plugin's thresholds,
and its readings as points (one per map cell for the full map). The files are kept in the QGIS profile folder
(`valetudo_wifi_maps/`), so a saved project finds them again; loading the same run
again replaces its layers. It needs key-based login from your PC to the Pi.

Output goes to `~/valetudo_wifi` (`--out` to change; then set the same folder in the
plugin's *Raspberry Pi* settings). Thresholds, cell size and IDW
coefficient have options (`--help`); `--all` rebuilds every run (e.g. after
changing a threshold). Run names come from the robot's clock, shown in the Pi's
time zone: keep the robot synchronised (Valetudo's NTP settings) and set the Pi's
time zone (`sudo timedatectl set-timezone Europe/Paris`).

**Terminal** tab, *Console* (Robot): type a command, press Enter, and it runs on the robot
(`ssh <user>@<robot>`, same key-based login and settings as the reboot); its
output appears below, errors in red, with the exit code when it is not 0. The
session opens when the tab is first shown and stays open while the panel is
visible, so `cd` carries over from one command to the next (shown in the prompt);
↑ and ↓ recall previous commands. It is not a full terminal (QGIS cannot give ssh
one): one command at a time, nothing can be typed into a running command, and
interactive programs (`vi`, `top`, `less`) do not work: use e.g. `top -b -n 1`.
Variables set with `export` do not carry over. *Stop* ends a command that does not
finish (e.g. `tail -f`) by opening a new session.

**Terminal** tab, *Raspberry Pi*: the same console and log on a Raspberry Pi (or any Linux machine
of your network, e.g. the one that builds the Wi-Fi maps). Set its address, SSH
user (`pi` by default) and port in *Settings > Options > Valetudo*, tab *Raspberry
Pi*; the *Raspberry Pi* switch of the Terminal tab, the Pi's details under the
strip and its card in the System tab appear once an address is set. Its *Log*
follows `~/valetudo/collect.log`, the log of the Pi's Wi-Fi collector (see its cron
line). It also needs key-based login from your PC: `ssh-copy-id pi@192.168.50.1`.

**Home Assistant** (*Settings > Options > Valetudo*, tab *Home Assistant*): the
address of your Home Assistant server (`http://localhost:8123/` by default) and a
long-lived access token (optional: without it the plugin can only check that Home
Assistant answers), created in Home Assistant on your profile page
(*Security > Long-lived access tokens*). The token is stored encrypted in the QGIS
authentication database (QGIS may ask for its master password). **Test
connection** reads the server's name and version.

**Terminal** tab, *Home Assistant*: a console and a log on your Home Assistant
server. Set its SSH address, user (`root` by default) and port in *Settings >
Options > Valetudo*, tab *Home Assistant*; the switch is greyed out without an
address. Login is by SSH key only: on Home Assistant OS, install the *Terminal &
SSH* add-on, paste your public key (`~/.ssh/id_ed25519.pub`) in its
`authorized_keys` option and set its SSH port in the add-on's *Network* settings.
The *Log* runs a command rather than following a file, `ha core logs -n 200 -f` by
default (Home Assistant OS keeps its log in the system journal); change it in the
settings for another installation (e.g. `docker logs -f -n 200 homeassistant`).

**Boot log**: after *Reboot robot (SSH)…*, or with *Watch robot boot* (e.g.
after using the power button), the plugin follows the robot's startup and
times each stage: offline, network up (SSH port answers), Valetudo answers
(version), robot firmware ready (state, battery), camera stream available, then
the total boot time and the end of Valetudo's own log. Lines go to the
*Valetudo* tab of the QGIS *Log Messages* panel and to the *Boot log* section of
the status panel (Info tab).

Actions the robot does not support are greyed out. Zone and go-to tools need the
map to be shown first, and switch back to the Pan tool after each use.

The map is displayed in the robot's own frame, in centimetres. The API reference
is the Swagger UI embedded in the robot: `http://<robot-ip>/swagger/`.

## Code layout

| File                         | Role                                                    |
|------------------------------|---------------------------------------------------------|
| `__init__.py`                | Entry point called by QGIS (`classFactory`)             |
| `metadata.txt`               | Name, version, QGIS compatibility                       |
| `plugin.py`                  | Toolbar, menu, wiring between client and layers         |
| `client.py`                  | Asynchronous HTTP calls to the Valetudo API             |
| `ha_client.py`               | Calls to the Home Assistant REST API                    |
| `map_layers.py`              | Map JSON -> QGIS layers, incremental updates            |
| `status_panel.py`            | Dockable status panel with controls                     |
| `camera.py`                  | H.264 stream decoding through an ffmpeg subprocess      |
| `camera_widget.py`           | Camera video widget, embedded in the status panel       |
| `boot_monitor.py`            | Follows and times the robot's boot, stage by stage      |
| `ssh_reboot.py`              | Robot reboot over SSH (key-based, non-blocking)         |
| `log_tail.py`                | Follows the robot's Valetudo log over SSH (`tail -f`)   |
| `ssh_console.py`             | SSH command session (one command at a time)             |
| `console_tab.py`             | A console tab of the panel (robot, Raspberry Pi)        |
| `pi_maps.py`                 | Loads the newest Wi-Fi map built on the Pi              |
| `panel_widgets.py`           | Signal graph, full-screen video, tab badges             |
| `schedule_view.py`           | Week view of the scheduled cleanings                    |
| `log_tab.py`                 | A log view of the Terminal tab (tail -F over SSH)       |
| `map_overlay.py`             | Status card over the map canvas                         |
| `host_info.py`               | Header lines: address, clock, uptime (robot and Pi)     |
| `schedule.py`                | Valetudo timers: UTC <-> local days and time            |
| `timer_dialog.py`            | Editor of one scheduled cleaning (`ui/timer_dialog.ui`) |
| `rooms_tree.py`              | Checkable rooms tree with room groups (panel, editor)   |
| `robot_survey.py`            | Installs / starts / reads the Wi-Fi recorder over SSH   |
| `robot/valetudo_wifi_survey.sh` | Wi-Fi recorder that runs on the robot (BusyBox sh)   |
| `restrictions.py`            | Editable no-go zones / virtual walls and their payload  |
| `wifi_survey.py`             | Wi-Fi survey: signal readings as points, IDW map        |
| `goto_emulation.py`          | "Go here" via a tiny zone clean + pause on arrival      |
| `quiet_travel.py`            | Quiet presets for "Go to", restored afterwards          |
| `room_groups.py`             | Room groups file (valetudo_room_groups.ini)             |
| `map_tools.py`               | Map tools: draw a cleaning zone, pick a go-to target    |
| `coords.py`                  | Frame conversion (the only place that flips the Y axis) |
| `settings.py`                | Setting keys, defaults and `load_settings()`            |
| `options_page.py`            | The Valetudo page of *Settings > Options*               |
| `ui_loader.py`               | Loads the Qt Designer forms of `ui/`                    |
| `ui/settings_page.ui`        | Layout of the settings page (Qt Designer)               |
| `ui/status_panel.ui`         | Layout of the status panel (Qt Designer)                |
| `i18n.py`                    | `tr()` helper and translator loading                    |
| `i18n/valetudo_qgis_fr.ts`   | French translation (Qt Linguist format)                 |

## Editing the forms

The settings page and the status panel are laid out in Qt Designer files
(`valetudo_qgis/ui/*.ui`); open them with Qt Designer, or with *QGIS Designer*
(shipped with QGIS, it knows the QGIS widgets). The Python code only fills them
at run time (rooms, consumables, dock components, the command buttons) and wires
them.

- Keep the object names: each module lists the ones it uses in `UI_WIDGETS`,
  and loading fails with a clear message if one is missing.
- Leave the form's *class* (top of the object inspector, `<class>` in the file)
  as `ValetudoQgis`: it is the translation context, shared with `tr()`.
- Visible texts are translated like the code's strings; mark texts that must not
  be translated (units, examples, `—`) as not translatable.
- `python3 scripts/check_ui.py` loads every form and checks the names the code
  uses (needs PyQt5, not QGIS; also run in CI).

## Translations

- Every user-facing string is written in English and wrapped in `tr("...")`
  (from `valetudo_qgis/i18n.py`), with a string literal as argument, or typed in a
  Qt Designer form.
  Use named placeholders and `.format()`: `tr("Command “{command}” sent.").format(command=...)`.
- Add each new string to `valetudo_qgis/i18n/valetudo_qgis_fr.ts` (by hand or with
  Qt Linguist).
- `python3 scripts/check_translations.py` lists missing translations (also run in CI).
- `python3 scripts/check_names.py` reports undefined names, e.g. a missing import
  (also run in CI).
- `scripts/compile_translations.sh` builds the `.qm` files. They are not committed.

To add a language, copy the `.ts` file to `valetudo_qgis_<lang>.ts`, set its
`language` attribute and translate the entries.

## Roadmap

- Option to keep the robot centred during live tracking.
- Replace polling with Valetudo's SSE stream.

## License

GPL v2 or later — see [LICENSE](LICENSE).
