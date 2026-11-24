# HomeQGIS

*Domotique* + QGIS: a home control centre in QGIS. It started as a learning
project to display and control a [Valetudo](https://valetudo.cloud) robot vacuum
from QGIS (through Valetudo's local REST API, no cloud), and now also watches and
drives the home servers around it: a Raspberry Pi, Home Assistant, a NUC and Kodi.

Available in English and French (the UI follows the QGIS interface language).

## Installation

**From a build (recommended):** each push to `main` builds a ready-to-install zip,
with compiled translations, in the *Actions* tab of this repository (artifact
`homeQGIS`). Unzip the downloaded artifact once to get `homeQGIS.zip`,
then in QGIS: *Plugins > Manage and Install Plugins > Install from ZIP*.

**For development:**

1. In QGIS: *Settings > User Profiles > Open Active Profile Folder*.
2. Go to `python/plugins/` (create it if needed).
3. Copy the `homeQGIS` folder of this repository there, or better, symlink it
   so that every `git pull` is picked up directly.
4. Optional, for the French UI: run `scripts/compile_translations.sh`
   (needs Qt's `lrelease`).
5. Restart QGIS and enable "Valetudo" in *Plugins > Manage and Install Plugins > Installed*.

Tip: install the **Plugin Reloader** plugin to reload the code after each change
without restarting QGIS.

**Building the zip:** `make zip` gives `dist/homeQGIS-<version>.zip` (checks,
French translation and manual included); `make` lists the other commands
(`check`, `install`, `release`, `clean`).

## User manual

**[sylsta.github.io/homeqgis](https://sylsta.github.io/homeqgis/)**, also
inside the plugin: *Plugins › HomeQGIS › User manual*, or *User manual* in the
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

Inside `homeQGIS/`, one subpackage per feature; the data folders (`ui/`, `icons/`,
`i18n/`) stay at the top.

| Path | Role |
|------|------|
| `__init__.py`, `plugin.py` | Entry point (`classFactory`); toolbar, menu, wiring between client, layers and panel |
| `metadata.txt` | Name, version, QGIS compatibility |
| `ui/`, `icons/`, `i18n/` | Qt Designer forms, icons, French translation (`homeqgis_fr.ts`) |
| **`core/`** | **Shared plumbing** |
| `settings.py`, `options_page.py`, `setup_wizard.py` | Setting keys and `load_settings()`; the page in *Settings › Options*; first-start wizard |
| `i18n.py`, `icons.py`, `ui_loader.py`, `paths.py` | `tr()`, icons, forms of `ui/`, the plugin's folder |
| `coords.py` | Frame conversion (the only place that flips the Y axis); the robot's CRS in cm |
| `project_layers.py` | Our layers found again in a project, saved next to it |
| `config_backup.py`, `about.py`, `manual.py` | Configuration backup (JSON), About page, user manual |
| **`valetudo/`** | **The robot's API and what is built on it** |
| `client.py`, `sse.py` | Asynchronous calls to the Valetudo API; live state and map (server-sent events) |
| `robot_settings.py`, `box.py`, `boot_monitor.py` | Maintenance tab: robot settings, Valetudo itself; boot timing |
| `goto_emulation.py`, `quiet_travel.py`, `drive_dialog.py` | "Go here" without the capability, quiet go-to, driving by hand |
| `schedule.py`, `schedule_view.py`, `timer_dialog.py` | Scheduled cleanings: timers, week view, editor |
| **`map/`** | **The robot's map in QGIS** |
| `layers.py`, `overlay.py`, `tools.py` | Map JSON → layers; status card over the canvas; zone / go-to / room tools |
| `restrictions.py`, `rooms_tree.py`, `room_groups.py` | No-go zones and virtual walls; rooms tree and room groups |
| `admin.py`, `changes.py` | Map snapshots, pending map, mapping pass, reset; map changes and walls |
| `floor_insights.py`, `insight_styles.py`, `obstacle_diary.py` | Days since cleaned, trouble spots, the obstacle diary |
| **`camera/`** | **The robot's camera** |
| `stream.py`, `widget.py`, `recorder.py` | H.264 decoding with ffmpeg, the video widget, MP4 recording |
| `views.py`, `recordings.py` | Frames along the way on the map; the recordings browser |
| **`history/`** | `logic.py`, `store.py`, `recorder.py`, `tab.py`: outings computed, stored per day, recorded, browsed |
| **`wifi/`** | `survey.py`, `robot_survey.py` (+ `valetudo_wifi_survey.sh`, run on the robot), `pi_maps.py`: Wi-Fi maps |
| **`home/`** | **Home Assistant** |
| `ha_client.py`, `ha_home.py`, `ha_history.py` | REST client; devices; history and stats (no Qt) |
| `ha_block.py`, `tab.py`, `detail.py`, `sensors.py` | Status frame, Home tab and its detail pane, sensors on the map |
| **`servers/`** | **The servers** |
| `model.py`, `editor.py`, `frames.py`, `host_info.py` | The list of servers, its settings tab, Status frames, header lines |
| `ssh_auth.py`, `ssh_host_block.py`, `ssh_console.py`, `ssh_reboot.py` | SSH password helper, a server read over SSH, console, robot reboot |
| `console_tab.py`, `log_tab.py`, `log_tail.py`, `system_terminal.py` | Terminal tab: consoles and logs; SSH in the system's terminal |
| `remote_desktop.py`, `wol.py`, `kodi_client.py`, `kodi_block.py` | VNC/RDP, Wake-on-LAN, Kodi |
| **`panel/`** | `status_panel.py`, `widgets.py`, `charts.py`: the dockable panel and its widgets |
| **`launcher/`** | `app.py`, `dialog.py`: HomeQGIS as an app (its own QGIS profile) |

Outside the plugin: `pi/` (scripts for the Raspberry Pi), `scripts/` (checks),
`docs/` (the manual, MkDocs).

## Editing the forms

The settings page and the status panel are laid out in Qt Designer files
(`homeQGIS/ui/*.ui`); open them with Qt Designer, or with *QGIS Designer*
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
  (from `homeQGIS/i18n.py`), with a string literal as argument, or typed in a
  Qt Designer form.
  Use named placeholders and `.format()`: `tr("Command “{command}” sent.").format(command=...)`.
- Add each new string to `homeQGIS/i18n/homeqgis_fr.ts` (by hand or with
  Qt Linguist).
- `python3 scripts/check_translations.py` lists missing translations (also run in CI).
- `python3 scripts/check_names.py` reports undefined names, e.g. a missing import
  (also run in CI).
- `scripts/compile_translations.sh` builds the `.qm` files. They are not committed.

To add a language, copy the `.ts` file to `homeqgis_<lang>.ts`, set its
`language` attribute and translate the entries.

## Roadmap

- Option to keep the robot centred during live tracking.
- Replace polling with Valetudo's SSE stream.

## License

GPL v2 or later — see [LICENSE](LICENSE).
