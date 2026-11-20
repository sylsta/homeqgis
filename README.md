# DomotiQGIS

*Domotique* + QGIS: a home control centre in QGIS. It started as a learning
project to display and control a [Valetudo](https://valetudo.cloud) robot vacuum
from QGIS (through Valetudo's local REST API, no cloud), and now also watches and
drives the home servers around it: a Raspberry Pi, Home Assistant, a NUC and Kodi.

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

1. When no robot is set, QGIS offers it at start-up: **Open settings…** in the
   message bar. Otherwise: *Settings > Options > DomotiQGIS* (or *Plugins > DomotiQGIS > Settings…*, which opens
   that page), tab **Servers**: **Add** a *Valetudo robot*, enter its address (e.g.
   `http://192.168.1.23`), click **Test connection**, then **OK**. As for every Options
   page, *Cancel* saves nothing.

   **Servers** tab: the list of servers the plugin works with, in the order of the
   panel; there is none to begin with. **Add** one of a type: *Valetudo robot*,
   *Raspberry Pi*, *Home Assistant*, *Kodi*, *Linux computer* or *Web service* (any web
   interface: Uptime Kuma, a router…); **⧉** duplicates the selected one (tokens and
   passwords included), **－** removes it, **▲ ▼** reorder them. The selected server's
   settings are on the right: a name, *Show in the status strip*, and the fields of its
   type, with **Test connection**. *Runs on* (Home Assistant, Kodi, web services): the
   Linux computer or Pi it runs on; its address then takes that computer's host, with
   its own port, and SSH goes there. With several robots, *Robot in use* picks the one
   the panel and the map work with. Tokens and passwords are kept encrypted in the QGIS
   authentication database. The settings of earlier versions are turned into servers
   the first time. **Remote desktop** (Raspberry Pi, Linux and Windows computers): VNC,
   RDP or both, with their ports and user; *Through SSH* (on by default, except for
   Windows) opens an SSH tunnel first, so the VNC or RDP server can stay closed to the
   network. The Status tab's 🖥 button (its arrow: VNC or RDP) opens it in the system's
   program: the one set under *Remote desktop programs* (a command with `{host}`,
   `{port}`, `{user}`, `{userat}`), else the first found: Remmina, TigerVNC/TightVNC
   `vncviewer`, `xfreerdp` or KRDC on Linux; `mstsc` or a VNC viewer on Windows; the
   built-in Screen Sharing or Microsoft Remote Desktop on macOS. Kodi and web services
   get the remote desktop of the computer they run on. The panel shows each of them, in
   this order (Status tab, status strip, Terminal tab); the map, history and Wi-Fi tools
   use the robot in use, Home Assistant's sensors the first Home Assistant, the Pi's
   Wi-Fi maps the first Pi.
2. Open the **DomotiQGIS panel** (the only toolbar button, or *Plugins > DomotiQGIS*).
   The menu and the toolbar stay minimal: everything happens in the panel. The
   toolbar's commands are chosen in *Settings > Options > DomotiQGIS*, tab **UI
   configuration**, *Toolbar*: the panel, *Show on map*, *Clean everything*, *Dock*,
   *Clean a zone…*, *Go to…*, *Settings…*, and the map tools (shown while *Show on map*
   is on; the advanced ones only with *Advanced tools*).

The panel (titled *Connection*), from top to bottom:

```
┌──────────────────────────────────────────────────────────┐
│ (logo) [Cleaning] ▮▮▮▮▯ 82 % 12 min ⚠ │ (Pi)● (HA)● … [🗺][⚙][⋮] │  status strip
├──────────────┬──────────────┬────────────────────────────┤
│ 🤖 Robot     │ 🏠 Home      │ 🖥 Servers                  │  sections
├──┬───────────┴──────────────┴────────────────────────────┤
│🧹│ Clean     rooms tree, cleaning profile, buttons       │  Robot's side tabs
│📅│ Schedule  week view + list                            │  (order: settings,
│🕘│ History   outings by day or week, load, replay        │   UI configuration)
│📷│ Camera                                                │
│📶│ Wi-Fi     signal, colours, recordings, Pi maps        │
│🔧│ Maintenance  robot, consumables, dock, statistics,    │
│  │           boot log, events                            │
├──┴───────────────────────────────────────────────────────┤
│ [ Start cleaning all rooms ] [Dock]                      │  big button, at the bottom
└──────────────────────────────────────────────────────────┘
  🏠 Home: Home Assistant's devices, by area or by integration
  🖥 Servers: 📈 Status (a frame per server) · ⌨ Terminal (while open)
```

- **Sections**, at the top: **🤖 Robot** (the robot's side tabs below), **🏠 Home**
  and **🖥 Servers** (the *Status* and *Terminal* tabs). A section gets an orange dot
  when one of the ⚠ problems belongs to it.
- **🏠 Home**: Home Assistant's devices, read with one request every 15 s while the
  section is shown, grouped **by area** or **by integration** (Zigbee, Hue, Shelly…).
  Each area shows its temperature, humidity, open doors and motion; each device its
  main values, battery 🔋 and Zigbee link quality 📶, faded when unavailable, the battery
  in orange below 20 %; unfold a device for all its entities. **⏻** switches lights,
  plugs and switches on or off. A filter, *Problems only* (unavailable devices, low
  batteries, also listed by the ⚠) and *Other entities* (Home Assistant's own: sun,
  weather, automations, helpers…). Needs the Home Assistant server's access token.
- **Status strip**, always visible: the state, battery, the job in progress (time
  and area, only while the robot works), a ⚠ when something needs you (dock tank
  empty or full, worn consumable, robot error, wrong clock: hover it for the list,
  click it to open the right tab), then each server of the settings with *Show in the
  status strip* ticked, in their order, as its logo and a pill styled like the robot's
  state: green *On the air*, red *Off the air*, *Connecting…*, or *No token* (Home
  Assistant answering without an access token), or just a coloured dot (*UI
  configuration* tab of the settings, *Status strip*); hover it for the details. Then *Show on map*, **⚙**
  (the settings) and the ⋮ menu (Locate, Watch robot boot, Reboot, Settings, Refresh now, Compact mode,
  Advanced tools, About). The Wi-Fi signal is in the strip's tooltip. **Click the
  strip** for the *Status* tab (Servers section).
- **Status** tab, the detailed status of the servers: connection, robot model,
  Valetudo version and Wi-Fi, then the robot's address, its own clock (orange, with
  how far off, when it differs from the computer's by more than 2 minutes) and
  uptime, the state and battery, with *Show on map* on the first line; **Refresh
  all**, at the right of the tab's title, reads every server again (each also
  refreshes by itself); then **a frame per server of the settings**, in the order of
  their Servers tab (the robot's frame where the robot in use is), with its name:
  - *Raspberry Pi*, *Linux computer*: name and system, address, clock and uptime, and
    a line with its load, memory, disk and temperature, read over SSH (key, or the
    password stored for Home Assistant) every 30 s while the panel is visible;
  - *Home Assistant*: version, home name and time zone, its address, its own clock
    and its uptime (from the *Uptime* integration's `sensor.uptime`, if you have it),
    read every minute;
  - *Kodi*: its version and system, address, uptime and CPU temperature, and what is
    playing with its progress, **⏸ / ▶** and **⏹**, read over Kodi's JSON-RPC every 5 s
    (in Kodi, turn on *Settings > Services > Control > Allow remote control via HTTP*,
    with a username and password);
  - *Windows computer*: whether its SSH (when its OpenSSH server is ticked), else RDP
    or VNC port answers;
  - *Web service*: whether its address answers, every minute.

  A wrong clock (more than 2 minutes off) is shown in orange and listed by the ⚠.
- Each server's frame in the Status tab has a **🌐** button, which opens its web
  interface in your browser, and a **>_** button, which opens an SSH session in your
  system's terminal (hover them for the address or command). A button appears only
  where there is something to open:
  - Web: the robot opens Valetudo, Home Assistant its address, and Kodi its web
    interface (same address as its remote control; enable *Settings > Services >
    Control > Allow remote control via HTTP* and a web interface in Kodi). The Pi and
    the NUC have no standard web interface: set a *Web address* in their settings
    (tab *Servers*) if they run one, for example Cockpit on the NUC (`https://<NUC>:9090`), or,
    on the Pi, Uptime Kuma (port 3001, a dashboard watching all these servers),
    Glances (`glances -w`, port 61208) or Cockpit.
  - SSH: with each server's SSH settings; Kodi and web services use the computer they
    run on. The
    terminal is the one named by the `TERMINAL` environment variable, else
    `x-terminal-emulator` (Debian, MX Linux…), else the first known terminal found;
    Terminal on macOS, Windows Terminal (or a console) on Windows. The window stays
    open when the session ends, to read any error. Password logins type the password
    there. The small arrow beside >_ (robot, Pi, Linux computers, Home Assistant, a
    Windows computer with OpenSSH: console only) also offers
    *Console in QGIS* and *Log in QGIS*: the **Terminal** tab then appears, on that
    server, with a [Console | Log] switch; its ✕ hides it again.
- **Big button**, at the bottom of the panel, after the robot's state: *Start
  cleaning all rooms* when docked or idle, *Pause* while it works, *Resume* when
  paused; *Dock* next to it while away from the dock.
- **Side tabs**: icons, their names as tooltips, in the order set in *Settings > Options >
  DomotiQGIS*, tab **UI configuration** (drag them, or ▲ ▼; *Default order*); a tab gets an orange dot when one
  of the problems of the ⚠ belongs to it. Each tab's page starts with its title (its
  icon and name), which stays in place while the page scrolls; the Terminal's also
  names the server it is on.
- **Compact mode** (⋮ menu, off by default): only the strip and the big button;
  click the strip to unfold or fold the rest. The panel never folds by itself (when
  QGIS loses the focus or the mouse goes elsewhere).
- **Advanced tools** (⋮ menu, or a box in the settings' *Robot* tab): the Terminal
  (consoles and logs in QGIS), the Wi-Fi recorder on the robot, the boot watch and
  the editing of no-go zones. Off for a new installation, so that a first look is
  simpler; on if a robot was already set when this switch appeared.
- **Setup assistant** (*Plugins > DomotiQGIS*, and offered when QGIS starts without
  a robot): the robot's address with a test, then the other servers you have
  (Raspberry Pi, NUC, Home Assistant, Kodi); their logins are set in the settings.

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
  within a minute (*Settings > Options > DomotiQGIS*, tab *Robot*, *General*: "Show the robot on
  the map when QGIS starts with an empty project"); a project with layers is left
  untouched.
- While it is on, the map tools appear at the end of the DomotiQGIS toolbar: *Pick rooms on the map* (click a
  room to tick or untick it in the Clean tab, right-click it for its menu), *Edit
  no-go zones and walls*, *Send no-go zones and walls to robot…*; and a small
  **status card** (state, battery, job) sits in the map's top right corner, so the
  robot can be watched with the panel closed.
- **Saved with the project**: once the project is saved, the map (rooms, walls,
  floor) and its zones are kept in `<project folder>/map/robot_map.gpkg`, so they show
  when the project is reopened, even with the robot off; each version of the map
  (after a new mapping) is also kept as `robot_map_<map id>.gpkg`, the map id being the
  one the history's outings carry. The robot, its path and the sensors stay temporary
  layers, filled while the robot answers. The Wi-Fi survey points go to
  `<project folder>/wifi/robot_wifi.gpkg`, and the Wi-Fi map to
  `wifi/robot_wifi_signal.tif`. Reopening a project reuses its layers instead of
  adding a second set (duplicates left by older versions are removed).

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
window (Esc or a double-click closes it). **Record** saves the video to an MP4
file (H.264) until **Stop recording**; the status shows the elapsed time. It
records the images already decoded for the live view, at their size (*Video
width* in the settings) and real speed, so the robot gets no second connection.
The camera keeps running while recording, even after leaving the tab. The file is
a fragmented MP4: if QGIS is killed, it stays readable up to its last seconds.
Needs ffmpeg 5.1 or newer, with libx264.

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

**History** (on by default; *Settings > Options > DomotiQGIS*, tab *Robot*, *Record the
robot's outings*): as long as QGIS runs and the robot is configured, every outing (from
leaving the dock to coming back) is recorded, whether the panel is open or not, in
`<project folder>/history/robot_YYYY-MM-DD.gpkg`, one GeoPackage per day (an outing that
crosses midnight stays in the file of the day it started). Each file has three layers:

| Layer      | One feature per                           | Main attributes                                                                 |
|------------|-------------------------------------------|----------------------------------------------------------------------------------|
| `outings`  | outing (line)                             | start, end, duration, distance, activities, `job_type`, `scheduled`, rooms, area, result |
| `segments` | continuous activity within an outing (line) | `activity`, detail (rooms, zone, spot, whole home), `job_type`, `scheduled`    |
| `points`   | reading, about every 2 s while moving     | time, `activity`, state, battery, Wi-Fi signal, `source`                             |

`activity` is `cleaning`, `go_to`, `returning`, `manual`, `mapping` or `other`; `job_type`
is `vacuum`, `mop` or `both`; `scheduled` is true when the outing started within two
minutes of one of the robot's timers and not from the plugin. Time on the dock is not
recorded. The project must have been saved (the history folder sits next to it): until
then the outing is kept in memory, and a message offers to save the project.

**History** tab (clock icon, after *Schedule*): the outings of a day or a week (◀ ▶,
*Today*), with their start (⏰ when started by a schedule), duration, activities, job,
rooms and how they ended, and the totals. Selecting an outing already on the map selects
it and zooms to it. **Load on map** (or a double-click) adds the day, or the whole week,
under *Robot history > Week NN · YYYY > day*: segments coloured by activity over a light
halo of each outing, and the points, hidden at first. **Replay** shows the selected outing
(or the day) in QGIS's Temporal Controller in about 30 seconds: the points appear as the
robot went, the day's other layers are hidden meanwhile. Layers already on the map are
refreshed as new readings are written.

**Outings made while QGIS was closed**: the history takes them from two other sources.
When the Wi-Fi recorder is installed on the robot (Wi-Fi tab), it records the robot's
position and state on the robot itself whenever it moves; each time the plugin connects
(or with **From the robot** in the History tab), its readings are added for the times
QGIS was not recording (`source` = `robot`). Runs already in the history are skipped,
and the times are corrected when the robot's clock is off. These outings have no job
type, rooms or result: the recorder only sees the robot move. And when QGIS starts
while the robot is out, or misses part of an outing, the outing's line is taken from
Valetudo's own path of the job when it is longer (`source` = `live+path`).

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
run, or the full map when **Full map (all runs)** (just under the button) is ticked, (the Pi as set in *Settings > Options > DomotiQGIS*, tab *Servers*) and
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
user (`pi` by default) and port in *Settings > Options > DomotiQGIS*, tab *Servers*,
*Raspberry Pi*; the Pi's frame in the Status tab (with its >_ menu) and its pill in
the strip appear once an address is set. Its *Log*
follows `~/valetudo/collect.log`, the log of the Pi's Wi-Fi collector (see its cron
line). It also needs key-based login from your PC: `ssh-copy-id pi@192.168.50.1`.

**Servers** tab of the settings: the list on the left (Raspberry Pi, Home Assistant,
NUC, Kodi), the selected server's settings on the right, each with a **Test
connection**. For the Raspberry Pi, it logs in over SSH with the values being edited
and shows the Pi's name and system, and how many Wi-Fi maps its folder holds. Home
Assistant and Kodi have an **On the NUC** box: their address then takes the NUC's
(with their own port), so that it is entered once. Leave it unticked for Home
Assistant OS in a virtual machine, which has its own address.

**Home Assistant** (*Settings > Options > DomotiQGIS*, tab *Servers*, *Home Assistant*): the
address of your Home Assistant server (`http://localhost:8123/` by default) and a
long-lived access token (optional: without it the plugin can only check that Home
Assistant answers), created in Home Assistant on your profile page
(*Security > Long-lived access tokens*). The token is stored encrypted in the QGIS
authentication database (QGIS may ask for its master password). **Test
connection** reads the server's name and version.

**Terminal** tab, *Home Assistant*: a console and a log on your Home Assistant
server, over SSH as `root` by default, on Home Assistant's own host unless you set
another SSH address (user and port too) in *Settings > Options > DomotiQGIS*, tab
*Servers*, *Home Assistant*. In the Status tab, the arrow of Home Assistant's 🌐
button also opens the Supervisor's web interface (`http://<Home Assistant host>:4327`). On Home Assistant OS, install the *Terminal & SSH* add-on and set its SSH
port in the add-on's *Network* settings, then either paste your public key
(`~/.ssh/id_ed25519.pub`) in its `authorized_keys` option, or set a password in
its options and in the plugin's *SSH password* field. The password is stored
encrypted in the QGIS authentication database, like the token, and handed to
`ssh` through `SSH_ASKPASS` (OpenSSH 8.4 or newer): it never appears on a command
line or in a file. Empty, the key is used.
The *Log* runs a command rather than following a file, `ha core logs -n 200 -f` by
default (Home Assistant OS keeps its log in the system journal); change it in the
settings for another installation (e.g. `docker logs -f -n 200 homeassistant`).

**Backup** tab (*Settings > Options > DomotiQGIS*): **Save now** writes the whole
configuration to a new file named with its date and time,
`valetudo_qgis_config_YYYYMMDD_HHMMSS.json` (all the plugin's settings, the room
groups and the panel's choices), in a folder of your choice (by default
`valetudo_backups` in the QGIS profile folder). It first applies the values on
screen, as OK does. The list shows the saved files, newest first: **Load
selected…** (or a double-click) or **Load a file…** replaces the configuration at
once, after a confirmation. Tokens and passwords stay out of the files unless you
tick *Include tokens and passwords*: they are then written in clear (the file is
made readable by you only). **Reset config** goes back to the default settings
(and removes the tokens, passwords and room groups) after saving a backup, so it
can be undone with *Load selected…*.

**Terminal** tab, *NUC*: a console and a log on the NUC, with its SSH settings
(tab *Servers*, *NUC*). The log follows the system log: the journal (`journalctl`) where
systemd runs, else `/var/log/syslog` (sysvinit, as MX Linux by default); set
another *Log command* in the settings if needed. Reading the system log may need
`root` or a user in the `adm` group.

**About** (tab *About* of the settings, or *About…* in the panel's ⋮ menu): what
the plugin does, in foldable sections (the robot, then the Raspberry Pi, Home
Assistant, NUC and Kodi), links to this repository and to Valetudo, the author and
licence (from `metadata.txt`), and the system it runs on (QGIS, Qt, Python, and
whether `ffmpeg` and `ssh` are found), with **Copy system information** for a bug
report.

**Boot log**: after *Reboot robot (SSH)…*, or with *Watch robot boot* (e.g.
after using the power button), the plugin follows the robot's startup and
times each stage: offline, network up (SSH port answers), Valetudo answers
(version), robot firmware ready (state, battery), camera stream available, then
the total boot time and the end of Valetudo's own log. Lines go to the
*DomotiQGIS* tab of the QGIS *Log Messages* panel and to the *Boot log* section of
the status panel (Info tab).

Actions the robot does not support are greyed out. Zone and go-to tools need the
map to be shown first, and switch back to the Pan tool after each use.

The map is displayed in the robot's own frame, in centimetres. The API reference
is the Swagger UI embedded in the robot: `http://<robot-ip>/swagger/`.

**Uptime Kuma on the Raspberry Pi** (optional): a dashboard on the Pi that watches
the robot, its SSH, Mosquitto, Home Assistant, the NUC, Cockpit and Kodi, with a
history and notifications (e.g. through Home Assistant). Install it without
Docker (Docker rewrites the firewall and would block the Pi's routing between its
Ethernet port and its Wi-Fi access point): Node.js 20.4 or newer (Debian trixie's
is enough), then

```sh
cd ~ && git clone https://github.com/louislam/uptime-kuma.git
cd uptime-kuma && npm run setup
sudo npm install -g pm2 && pm2 install pm2-logrotate
pm2 start server/server.js --name uptime-kuma
pm2 save && pm2 startup     # then run the "sudo env PATH=…" line it prints
```

`pi/uptime_kuma_monitors.js` then adds the monitors: it chooses the SQLite
database on a first run, creates the admin account if there is none (or logs in),
asks for the addresses and adds the monitors not there yet (it can be run again).
Run it on the Pi with `node uptime_kuma_monitors.js`. In the plugin, set the Pi's
*Web address* to `http://<Pi>:3001`: the Pi's 🌐 button in the Status tab opens it.

## Code layout

| File                         | Role                                                    |
|------------------------------|---------------------------------------------------------|
| `__init__.py`                | Entry point called by QGIS (`classFactory`)             |
| `metadata.txt`               | Name, version, QGIS compatibility                       |
| `plugin.py`                  | Toolbar, menu, wiring between client and layers         |
| `client.py`                  | Asynchronous HTTP calls to the Valetudo API             |
| `ha_client.py`               | Calls to the Home Assistant REST API                    |
| `ssh_auth.py`                | Optional SSH password (SSH_ASKPASS helper)              |
| `ssh_host_block.py`          | A server read over SSH, in the Status tab (the NUC)     |
| `kodi_client.py`             | Calls to Kodi's JSON-RPC (HTTP)                         |
| `kodi_block.py`              | Kodi in the Status tab: state, playback, remote         |
| `config_backup.py`           | Save and load the configuration (timestamped JSON)      |
| `about.py`                   | About page (settings tab and ⋮ menu window)             |
| `system_terminal.py`         | SSH session in the system's terminal window             |
| `pi/uptime_kuma_monitors.js` | Adds the monitors to Uptime Kuma on the Pi (not part of the plugin) |
| `camera_recorder.py`         | Camera recording to MP4 (second ffmpeg process)         |
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
| `history_logic.py`           | Outings, segments and points from the robot's readings  |
| `history_store.py`           | Daily GeoPackages of the history (`<project>/history`)  |
| `history_recorder.py`        | Polls the robot and records its history                 |
| `history_tab.py`             | History tab: outings by day or week, load, replay       |
| `goto_emulation.py`          | "Go here" via a tiny zone clean + pause on arrival      |
| `quiet_travel.py`            | Quiet presets for "Go to", restored afterwards          |
| `room_groups.py`             | Room groups file (valetudo_room_groups.ini)             |
| `map_tools.py`               | Map tools: draw a cleaning zone, pick a go-to target    |
| `project_layers.py`          | Our layers found again in a project, saved next to it   |
| `servers.py`                 | The servers: types, fields, storage, earlier settings   |
| `servers_editor.py`          | Servers tab of the settings                             |
| `remote_desktop.py`          | VNC and RDP in the system's program, SSH tunnel         |
| `server_frames.py`           | A Status tab frame per server; web and port checks      |
| `ha_block.py`                | Home Assistant's frame                                  |
| `ha_home.py`                 | Home Assistant's devices: template, grouping, summaries |
| `home_tab.py`                | The panel's Home section                                |
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
