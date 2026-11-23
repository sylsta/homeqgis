# Installation

## Requirements

- **QGIS 3.38 or newer** (Qt 5 or Qt 6).
- A robot vacuum running **[Valetudo](https://valetudo.cloud)**, reachable on your
  network.
- Optional, depending on what you use:

| For | You need |
|---|---|
| Camera, video recording | **ffmpeg** (5.1 or newer, with libx264 for recording) |
| Reboot, consoles, logs, server status | an **SSH client** and key-based login to the machines |
| Home section, sensors on the map | a **Home Assistant** long-lived access token |
| Remote desktop | a VNC or RDP program (Remmina, TigerVNC, xfreerdp, mstsc…) |

## From a build (recommended)

Each change on GitHub builds a ready-to-install zip, with the French translation
and this manual included.

1. On the [repository's *Actions* page](https://github.com/sylsta/qgis-valetudo/actions),
   open the latest successful **Build plugin** run.
2. Download the **valetudo_qgis** artifact and unzip it once: you get
   `valetudo_qgis.zip`.
3. In QGIS: *Plugins › Manage and Install Plugins › Install from ZIP*, choose that
   file, then **Install Plugin**.

## For development

1. In QGIS: *Settings › User Profiles › Open Active Profile Folder*.
2. Go to `python/plugins/` (create it if needed).
3. Copy the `valetudo_qgis` folder of the repository there, or better, make a
   symbolic link to it, so that every `git pull` is picked up.
4. Optional, for the French interface: `scripts/compile_translations.sh` (needs
   Qt's `lrelease`).
5. Restart QGIS and enable **DomotiQGIS** in *Plugins › Manage and Install Plugins ›
   Installed*.

!!! tip
    The **Plugin Reloader** plugin reloads the code after a change without
    restarting QGIS.

## Building the zip yourself

From the repository, with `python3`, `zip`, Qt's `lrelease` and mkdocs (with
mkdocs-material):

| Command | What it does |
|---|---|
| `make` | lists the commands, with the version |
| `make check` | the same checks as GitHub (syntax, names, translations, forms) |
| `make zip` | `dist/valetudo_qgis-<version>.zip`: checks, French translation, user manual inside |
| `make install` | copies the plugin into a QGIS profile (`PROFILE=default`) |
| `make release` | the zip of a committed and pushed `main`, tagged `v<version>` (raise `version` in `metadata.txt` first) |
| `make clean` | removes what the build made |

`make release` tags locally; it then says how to push the tag and attach the zip
to a GitHub release.

## Updating

Install the new zip the same way: QGIS replaces the plugin. Your settings, room
groups and history are kept. Before a big update, a
[configuration backup](settings.md#backup) does no harm.
