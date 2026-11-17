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

The panel, from top to bottom:

```
Eureka J15 Pro Ultra · Connected        [Docked]
████████████████████ 99 %
⚠ error, only when there is one
┌ Clean ─────────────────────────────────────┐
│ ▾ ☐ All rooms                              │
│     ☐ Hallway                              │
│     ☐ Kitchen                              │
│ [Clean everything] [Clean room(s)]         │
│ [Clean a zone…]    [Go to…]                │
└────────────────────────────────────────────┘
┌ Robot ─────────────────────────────────────┐
│ [Pause]   [Dock]   [Locate]                │
└────────────────────────────────────────────┘
┌ Dock station ── (only if supported) ───────┐
│ [Empty bin] [Wash mops] [Dry mops]         │
└────────────────────────────────────────────┘
[Show on map]     map + live tracking + robot kept in view
Result of the last command
Robot · Camera · Maintenance · Advanced · Log   (tabs)
```

- Every button does one thing; its tooltip says what. *Clean a zone…* and *Go to…*
  stay pressed until you have drawn the zone or clicked the point on the map.
- Rooms are a checkable tree: *All rooms*, then your own **room groups**. Ticking
  a group ticks its rooms (partial when only some are); a room in several groups
  is the same room, ticked everywhere and cleaned once. *Clean room(s)* cleans the
  ticked rooms.
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
- **Edit rooms**: right-click a room → *Rename…*, *Join with ▸* another
  room, or *Split with a line on the map…* (click the two ends of the cut line,
  from wall to wall; right-click or Esc cancels). Each edit asks for confirmation;
  the room list and the map are then reloaded. If the robot refuses (e.g. a split
  line that does not cross the room), its own message is shown.
- **Show on map** loads the map, refreshes the robot live and keeps it in view
  (recentring only when it nears the edge). Click again to stop.
- **Tabs**: Robot (state details, dock station states, fan speed and water usage,
  attachments, position), Camera (live video, plays only while this tab is shown;
  camera light), Maintenance (consumables, statistics), Advanced (tools: no-go
  zones and walls, watch boot, reboot; Wi-Fi, events, boot log, features), Log
  (Valetudo's log file, live).
- **Go to…** on robots without Valetudo's go-to (e.g. Eureka J15 Pro Ultra): a 60 cm
  zone clean at that spot, then a pause as soon as the robot is within 50 cm (it
  cleans on its way; a first-time confirmation says so).

The panel refreshes itself while visible (every 5 s while the robot works, every
30 s otherwise), even when the robot is docked. Sections fold with their arrow
(remembered).

**Camera**: robots that expose a raw H.264 stream over TCP (default
`tcp://<robot>:8555`). Needs **ffmpeg** (found in the `PATH`, or set its path in
the settings). The stream reconnects by itself if it drops, and **Save snapshot**
saves the current image as PNG.

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

**Wi-Fi survey** (Advanced tab): *Record Wi-Fi survey* reads the robot's Wi-Fi
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

**Reboot robot (SSH)…** (Valetudo menu and status panel): Valetudo deliberately
has no reboot API, so the plugin runs `ssh <user>@<robot> reboot` after a
confirmation. It needs an SSH client and key-based login to the robot
(`ssh-copy-id root@<robot>`); no password is ever stored or asked for. SSH user
and port are in the settings (`root`, 22 by default).

**Log** tab: follows Valetudo's log file on the robot, `/tmp/valetudo.log`, as
`ssh root@<robot> 'tail -f /tmp/valetudo.log'` would (last 200 lines, then new
ones as they come; errors in red, warnings in orange). It only runs while the tab
is shown and the panel is visible, uses the same key-based SSH login and settings
as the reboot, and reconnects by itself 10 s after the link drops (e.g. while the
robot reboots). *Scroll to new lines* keeps the newest line in view; untick it to
read older lines in peace. *Clear* empties the view (not the file).

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
| `map_layers.py`              | Map JSON -> QGIS layers, incremental updates            |
| `status_panel.py`            | Dockable status panel with controls                     |
| `camera.py`                  | H.264 stream decoding through an ffmpeg subprocess      |
| `camera_widget.py`           | Camera video widget, embedded in the status panel       |
| `boot_monitor.py`            | Follows and times the robot's boot, stage by stage      |
| `ssh_reboot.py`              | Robot reboot over SSH (key-based, non-blocking)         |
| `log_tail.py`                | Follows the robot's Valetudo log over SSH (`tail -f`)   |
| `restrictions.py`            | Editable no-go zones / virtual walls and their payload  |
| `wifi_survey.py`             | Wi-Fi survey: signal readings as points, IDW map        |
| `goto_emulation.py`          | "Go here" via a tiny zone clean + pause on arrival      |
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
