# On the map

The robot's map is shown as real QGIS layers, in the robot's own frame (in
centimetres), in a *Valetudo* group:

| Layer | What |
|---|---|
| *Valetudo - map* | rooms, walls, floor (one colour per room, with its name) |
| *Valetudo - zones* | the robot's no-go and no-mop zones, as Valetudo shows them |
| *Valetudo - lines* | the robot's path, its predicted path, virtual walls |
| *Valetudo - robot* | the robot and its dock |
| *Valetudo - obstacles* | what the robot avoided: type, confidence, photo (see below) |
| *Valetudo - sensors* | Home Assistant sensors you placed |

![The robot's map in QGIS](images/map.png)

## Show on map

**🗺 Show on map** (in the status strip) loads the map and refreshes the robot live:
Valetudo pushes the map and the robot's state as they change, so the position, the
status and the dock follow within a second (when that live stream cannot be
opened, the plugin asks every few seconds instead, as before).
The map stays where you put it; to keep the robot in view (recentring only when it
nears the edge), tick *Keep the robot in view* in the settings, *UI configuration*.
Click again to stop.

In a project that has never been saved, it first offers to open the
[robot project](first-steps.md#the-robot-project), or to save this one as the robot
project: the map is kept next to it.

When QGIS starts without a project, it can open the robot project and turn Show on
map on once the robot answers (within a minute): tick *When QGIS starts without a
project, open the robot project…* in the settings, *Robot* tab, *General*. A project
you open yourself is left untouched.

While it is on:

- the **map tools** appear in the HomeQGIS toolbar (those ticked in the settings'
  [UI configuration](settings.md#ui-configuration));
- a small **status card** (state, battery, job) sits in the map's top right corner,
  so you can follow the robot with the panel closed.

## Measuring

The robot's frame is a coordinate system of its own, in centimetres (a transverse
Mercator centred on 0,0, exact to well under a millimetre over a home), and the
project measures on the plane (*Project › Properties › General*, ellipsoid *None*).
So QGIS's measure tool, the scale bar, `$length` and `$area` give real distances and
areas: choose metres in the measure tool. The plugin sets this when it shows the
map; layers made before it had no coordinate system and get this one.

Do not put an online base map (OpenStreetMap…) under it: the home would appear off
the coast of Africa, where 0,0 is. The robot's map is not georeferenced.

## Map tools

| Tool | What it does |
|---|---|
| ![](images/icon-pick-rooms.png){ width=20 } **Pick rooms on the map** | Click a room to tick or untick it in the Clean tab, which the panel then shows; right-click it for its menu (rename, join, split). |
| ![](images/icon-place-sensor.png){ width=20 } **Place a sensor on the map** | Click a point, choose a Home Assistant sensor: it shows there with its live value. Right-click a sensor to remove it. |
| ![](images/icon-edit-restrictions.png){ width=20 } **Edit no-go zones and walls** | Advanced tool, see below. |
| ![](images/icon-send-restrictions.png){ width=20 } **Send no-go zones and walls to robot…** | Advanced tool, see below. |

Zone and Go to tools (from the Clean tab) switch back to the Pan tool after each use.

## Sensors on the map

**Place a sensor on the map** needs the Home Assistant server's access token. It
lists Home Assistant's `sensor` and `binary_sensor` entities (temperature, humidity,
door, motion, leak…); the value is refreshed every 15 s while *Show on map* is on.
To move one, remove it and place it again. Positions are kept in the plugin's
settings, so they follow you from one project to another.

## No-go zones and virtual walls

*Edit no-go zones and walls* loads the robot's restrictions into two editable
layers: *no-go zones* (polygons, *No-go* or *No-mop*) and *virtual walls* (lines).
Edit them with the usual QGIS tools (add, move vertices, snapping, undo). A bar at
the top of the map offers **Send to robot…** (after a confirmation, they replace the
robot's restrictions) and **Discard changes**.

Valetudo needs 4 corners per zone and 2 points per wall: other shapes are converted
(bounding rectangle, line ends), and the confirmation says so.

## Obstacles

When the robot recognises obstacles (shoes, cables, pet waste…; robots with an AI
camera), Valetudo puts them on its map and the plugin shows them in *Valetudo -
obstacles*: orange triangles labelled with their type, outlined in white when the
robot took a photo. The attribute table gives `kind`, `confidence` (%) and
`photo`. **Show the photo** (an action of the layer: right-click the obstacle with
the Identify tool, or in the attribute table) asks the robot for it.

The robot does not see everything with its lidar as obstacles: only what it
recognised. Its raw lidar scans are not available (Valetudo does not have them).

## Obstacle diary

The map only shows the obstacles of the moment. The plugin keeps every one the
robot reports in *Obstacle diary* (`map/obstacle_diary.gpkg`, once the project is
saved): type, confidence, first and last seen, and its photo, downloaded once into
`map/obstacles/`. The points are semi-transparent: where things are often left on
the floor, they pile up and darken. Hover one (map tips on, *View › Show Map Tips*)
to see the photo, or use its action *Open the photo*. Filter the table on `kind`
("Sock", "Cable"…) or on a date to find something.

## Camera views

While the camera plays and the robot is out — every recorded job does it — the
plugin keeps a frame every metre, in *Camera views* (`views/` next to the
project): a small triangle where the robot was, pointing where it looked. Hover
it (map tips on) to see the image; its action *Open the image* opens it. A
street view of your home, at robot height. Untick *Place what the camera sees on
the map* in the settings (*Robot* tab, camera) to stop it; a job of a few hundred
metres keeps some hundreds of small images.

## What the history tells

From *Plugins › HomeQGIS*, over the last days you choose (30 by default):

- **Days since each place was cleaned…** — the floor coloured by how long since
  the robot last cleaned it: green today, then yellow, orange, red, and hatched
  dark red where it did not clean at all in those days. Its paths are widened to
  the strip it cleans (about 32 cm). The corners it never reaches show at once.
- **Where the robot has trouble…** — orange circles where it got stuck (it stayed
  within 30 cm for 45 s or more while working) and red crosses where it went
  into error. Where the circles pile up, something is in the way: a cable, a chair,
  the edge of a rug.

Both need the history, recorded by the plugin while QGIS runs (see
[History](robot/history.md)).

## Map changes

The plugin keeps the first map of each day in `map/versions/` (once the project
is saved). *Plugins › HomeQGIS › **Compare the map with an earlier day…*** shows
in a *Map changes since …* layer what differs from the map of the day you choose:

| Colour | Change |
|---|---|
| red | wall or furniture that was not there (a moved chair, a closed door) |
| blue | wall or furniture that went away |
| green | floor the robot now reaches |
| orange | floor it no longer reaches |

The map is redrawn at each run, so small shifts (about a pixel, 7.5 cm) and pieces
under 100 cm² of wall or 0.05 m² of floor are not counted as changes. The table
gives each change's area in m².

## The walls as lines

*Plugins › HomeQGIS › **Draw the walls as lines*** draws the outline of the floor,
simplified, in *Valetudo - wall lines*: the walls as seen from inside the rooms,
with their length in m, for plans and measurements. It is kept in
`map/robot_map.gpkg` once the project is saved; run it again after a new map.

## The robot's map itself

In *Plugins › HomeQGIS*, shown only for robots that offer them:

- **Map snapshots…** — the copies of its map the robot keeps (some Roborock
  robots): **Show on the map** draws one over the current map, in a *Map snapshot
  of …* layer, and **Restore…** puts it back on the robot (asked first).
- **New mapping pass…** — the robot explores the home to draw its map again,
  without cleaning (Eureka J15, some Midea, Dreame and Roborock robots).
- **Reset the map…** — deletes the robot's map, with its rooms and their names,
  the no-go zones and the schedules that clean given rooms (asked twice).

When the robot finds that the home has changed and draws a new map (some Dreame
robots), a message asks whether to **keep the new map** or **keep the old one**.
*Compare the map with an earlier day* helps to see what changed.

## Saved with the project

Once the project is saved:

- the map (rooms, walls, floor) and its zones are kept in
  `map/robot_map.gpkg` next to the project, so they show when the project is reopened,
  even with the robot off;
- each version of the map (after a new mapping) is also kept as
  `map/robot_map_<map id>.gpkg`; the outings of the history carry the same map id.

The robot, its path and the sensors stay temporary layers, filled while the robot
answers. Reopening a project reuses its layers instead of adding a second set.
