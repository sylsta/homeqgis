# Files

## Next to the project

Once the project is saved, the plugin writes in folders next to it:

```
my_house.qgz
history/
    robot_2026-11-20.gpkg        the robot's outings of the day (outings, segments, points)
    home_2026-11-20.gpkg         Home Assistant history you exported
map/
    robot_map.gpkg               the robot's current map (rooms, zones)
    robot_map_a3f9c2e1.gpkg      one per version of the map
wifi/
    robot_wifi.gpkg              the Wi-Fi survey points
    robot_wifi_signal.tif        the last Wi-Fi map built
```

Copy or move the whole folder with the project, and everything follows.

## In the QGIS profile folder

*Settings › User Profiles › Open Active Profile Folder*:

| File or folder | What |
|---|---|
| `valetudo_room_groups.ini` | your [room groups](robot/clean.md#rooms-and-room-groups) |
| `valetudo_backups/` | [configuration backups](settings.md#backup) (another folder can be chosen) |
| `valetudo_wifi_maps/` | Wi-Fi maps fetched from the Raspberry Pi |

The settings themselves are in QGIS's settings (under `valetudo/`), and the tokens
and passwords in the QGIS authentication database.
