# First steps

## The setup assistant

When QGIS starts and no robot is set, a message offers **Set up…**. The assistant
(also in *Plugins › DomotiQGIS › Setup assistant…*) asks:

1. **Your robot's address**, e.g. `http://192.168.1.23`, with a test.
2. **The other servers you have**: Raspberry Pi, NUC (Linux computer), Home
   Assistant, Kodi. Tick those you have and give their address.

**Finish** saves them and opens the panel. Everything can be changed later in the
settings.

![The setup assistant](images/setup-assistant.png)

## Adding the robot by hand

1. *Settings › Options › DomotiQGIS* (or *Plugins › DomotiQGIS › Settings…*).
2. Tab **Servers**: **Add › Valetudo robot**.
3. Enter its **Address** (e.g. `http://192.168.1.23`), then **Test connection**: it
   answers with the robot's model.
4. **OK**. As on every Options page, *Cancel* saves nothing.

See [Settings › Servers](settings.md#servers) for the other server types.

## Opening the panel

Click the DomotiQGIS button in the toolbar (or *Plugins › DomotiQGIS ›
DomotiQGIS panel*). The panel docks on the side of QGIS like any panel: drag its
title to move it, or float it in its own window.

Then click **🗺 Show on map** in the panel's status strip: the robot's map appears
in the current project, with the robot on it.

![The status strip, with Show on map](images/strip.png)

## Simple first, advanced later

A new installation hides the **advanced tools** (consoles and logs in QGIS, the
Wi-Fi recorder on the robot, the boot watch, the editing of no-go zones), so that
the first look stays simple. Turn them on in the panel's **⋮ › Advanced tools**,
or in the settings' *Robot* tab.

## Save the project

Several features write files **next to the project**: the robot's
[history](robot/history.md), its [map](map.md#saved-with-the-project), the
[Wi-Fi survey](robot/wifi.md). Save your project once (*Project › Save*) and they
start; until then the plugin keeps what it can in memory and reminds you.
