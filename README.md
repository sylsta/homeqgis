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

## User manual

**[sylsta.github.io/qgis-valetudo](https://sylsta.github.io/qgis-valetudo/)**, also
inside the plugin: *Plugins › DomotiQGIS › User manual*, or *User manual* in the
panel's ⋮ menu. Its sources are the Markdown files of [`docs/`](docs/), built with
[MkDocs](https://www.mkdocs.org/) (Material theme) by the CI, which publishes them and
puts them in the plugin zip.

To preview it while writing:

```sh
pip install "mkdocs>=1.6,<2" "mkdocs-material>=9.5,<10"
mkdocs serve        # then open http://127.0.0.1:8000
```

Screenshots are placeholders until taken: [`docs/images/SCREENSHOTS.md`](docs/images/SCREENSHOTS.md)
lists them; replace a placeholder PNG with the real one under the same name.

## In short

- **The robot**: its map as QGIS layers, live; cleaning by room, room group, zone or
  Go to; rooms and no-go zones edited with the QGIS tools; Valetudo's schedule; camera
  with recording; Wi-Fi surveys and maps; consumables and dock; a history of every
  outing, one GeoPackage per day, replayed with the Temporal Controller.
- **The home**: Home Assistant's devices by area or integration, with battery and
  Zigbee link quality, lights and plugs switched; graphs from its history, rooms
  compared, rooms coloured on the map over time.
- **The servers**: Raspberry Pi, Linux and Windows computers, Kodi, web services: a
  frame each with its state and resources; web interface, remote desktop (VNC, RDP)
  and SSH in one click; consoles and logs in QGIS.

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
| `ha_history.py`              | Home Assistant's history: series, stats, battery trend  |
| `charts.py`                  | Curves, timelines and small graphs (QPainter)           |
| `home_detail.py`             | Home section's detail pane: graphs, compare, export     |
| `manual.py`                  | Opens the user manual (inside the plugin, else online)  |
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
