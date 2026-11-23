"""Turns the Valetudo map into QGIS layers, and manages those layers.

Layers are created once, in a "Valetudo" group, ordered
robot > lines > zones > map. Afterwards only entities are refreshed; rooms
are recomputed only when the map itself has changed.
"""

import hashlib
import os

from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsExpression,
    QgsFillSymbol,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProperty,
    QgsRectangle,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from .coords import v2q
from .history_logic import map_fingerprint
from .i18n import tr
from . import map_changes
from .project_layers import (adopt, make_permanent, new_feature, project_folder,
                             replace_features, tag, write_gpkg)

GROUP_NAME = "Valetudo"
AREA_ENTITIES = {"no_go_area", "no_mop_area", "active_zone"}
POINT_ENTITIES = {"robot_position", "charger_location", "go_to_target"}
OBSTACLE = "obstacle"   # its own layer: what it is, how sure, its photo

# Valetudo's robot angle is in degrees, clockwise on screen (our Y flip keeps the
# on-screen orientation). If the arrow points the wrong way, adjust this offset.
ROBOT_ANGLE_OFFSET = 0

STR = QMetaType.Type.QString
DBL = QMetaType.Type.Double
INT = QMetaType.Type.Int
PLUGIN_PACKAGE = os.path.basename(os.path.dirname(os.path.abspath(__file__)))


def add_photo_action(layer):
    """An action on the obstacles layer (Identify, attribute table): the photo."""
    from qgis.core import QgsAction
    manager = layer.actions()
    if any(a.name() == tr("Show the photo") for a in manager.actions()):
        return
    code = ("from qgis.utils import plugins\n"
            f"p = plugins.get({PLUGIN_PACKAGE!r})\n"
            "if p is not None: p.show_obstacle_photo('[% \"obstacle_id\" %]')")
    action = QgsAction(QgsAction.ActionType.GenericPython, tr("Show the photo"), code,
                       "", False, "", {"Feature", "Canvas"})
    manager.addAction(action)


def layer_names():
    """Translated layer names, by role."""
    return {
        "rooms": tr("Valetudo - map"),
        "areas": tr("Valetudo - zones"),
        "lines": tr("Valetudo - lines"),
        "robot": tr("Valetudo - robot"),
        "sensors": tr("Valetudo - sensors"),
        "obstacles": tr("Valetudo - obstacles"),
    }


def _points_renderer():
    """One symbol per point type, so the robot is not confused with its dock."""
    def marker(**props):
        return QgsMarkerSymbol.createSimple({k: str(v) for k, v in props.items()})

    robot = marker(name="arrow", color="#e31a1c", outline_color="black", size=6)
    robot.setDataDefinedAngle(QgsProperty.fromExpression(
        f'coalesce("angle", 0) + {ROBOT_ANGLE_OFFSET}'))

    categories = [
        QgsRendererCategory("robot_position", robot, tr("Robot")),
        QgsRendererCategory("charger_location", marker(
            name="square", color="#33a02c", outline_color="black", size=4), tr("Dock")),
        QgsRendererCategory("go_to_target", marker(
            name="cross", color="#1f78b4", outline_color="#1f78b4",
            outline_width=0.8, size=5), tr("Go-to target")),
    ]
    return QgsCategorizedSymbolRenderer("type", categories)


# Soft colours, one per room (cycled), readable under black labels.
ROOM_COLORS = ["#a6cee3", "#b2df8a", "#fdbf6f", "#cab2d6", "#fb9a99", "#ffff99",
               "#8dd3c7", "#bebada", "#fccde5", "#ccebc5", "#ffed6f", "#d9d9d9"]
FLOOR_COLOR = "#eeeeee"
WALL_COLOR = "#455a64"


def _fill(color, outline="transparent", width=0.0, style="solid"):
    return QgsFillSymbol.createSimple({
        "color": color, "outline_color": outline, "outline_width": str(width),
        "style": style})


def _line(color, width, style="solid"):
    return QgsLineSymbol.createSimple({
        "line_color": color, "line_width": str(width), "line_style": style,
        "capstyle": "round", "joinstyle": "round"})


def _rooms_renderer(segment_ids):
    """Walls dark, floor light grey, each room its own soft colour."""
    cats = [QgsRendererCategory("wall", _fill(WALL_COLOR), tr("Walls")),
            QgsRendererCategory("floor", _fill(FLOOR_COLOR), tr("Floor"))]
    def key(seg_id):
        return (0, int(seg_id)) if str(seg_id).isdigit() else (1, str(seg_id))
    for i, seg_id in enumerate(sorted(segment_ids, key=key)):
        cats.append(QgsRendererCategory(
            f"segment:{seg_id}", _fill(ROOM_COLORS[i % len(ROOM_COLORS)], "#ffffff", 0.3),
            f"{tr('Room')} {seg_id}"))
    renderer = QgsCategorizedSymbolRenderer(
        "CASE WHEN \"type\" = 'segment' THEN 'segment:' || \"segment_id\" ELSE \"type\" END",
        cats)
    return renderer


def _lines_renderer():
    """Path thin and translucent, planned path dashed, virtual walls thick red."""
    return QgsCategorizedSymbolRenderer("type", [
        QgsRendererCategory("path", _line("30,136,229,170", 0.35), tr("Path")),
        QgsRendererCategory("predicted_path", _line("30,136,229,200", 0.35, "dash"),
                            tr("Planned path")),
        QgsRendererCategory("virtual_wall", _line("#c62828", 1.0), tr("Virtual wall")),
    ])


def _areas_renderer():
    return QgsCategorizedSymbolRenderer("type", [
        QgsRendererCategory("no_go_area", _fill("198,40,40,60", "#c62828", 0.5, "b_diagonal"),
                            tr("No-go")),
        QgsRendererCategory("no_mop_area", _fill("21,101,192,60", "#1565c0", 0.5, "b_diagonal"),
                            tr("No-mop")),
        QgsRendererCategory("active_zone", _fill("67,160,71,50", "#2e7d32", 0.6),
                            tr("Zone being cleaned")),
    ])


def _room_labeling():
    """Label each room with its Valetudo name, or "Room <id>" when it has none."""
    fallback = QgsExpression.quotedString(tr("Room"))
    settings = QgsPalLayerSettings()
    settings.isExpression = True
    settings.fieldName = (
        "CASE WHEN \"type\" = 'segment' "
        f"THEN coalesce(\"name\", {fallback} || ' ' || \"segment_id\") END"
    )
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.8)
    buffer.setColor(QColor("white"))
    buffer.setOpacity(0.8)
    fmt = QgsTextFormat()
    fmt.setSize(9)
    fmt.setColor(QColor("#212121"))
    font = fmt.font()
    font.setBold(True)
    fmt.setFont(font)
    fmt.setBuffer(buffer)
    settings.setFormat(fmt)
    settings.centroidInside = True    # label inside the room, even for odd shapes
    return QgsVectorLayerSimpleLabeling(settings)


def _obstacles_renderer():
    """Orange triangles; outlined in white when the robot took a photo."""
    return QgsCategorizedSymbolRenderer("photo", [
        QgsRendererCategory(1, QgsMarkerSymbol.createSimple(
            {"name": "triangle", "color": "#ff7f00", "outline_color": "white",
             "outline_width": "0.6", "size": "4"}), tr("Obstacle (photo)")),
        QgsRendererCategory(0, QgsMarkerSymbol.createSimple(
            {"name": "triangle", "color": "#ff7f00", "outline_color": "black",
             "size": "3.5"}), tr("Obstacle")),
    ])


def _obstacle_labeling():
    settings = QgsPalLayerSettings()
    settings.fieldName = "kind"
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.6)
    buffer.setColor(QColor("white"))
    fmt = QgsTextFormat()
    fmt.setSize(7)
    fmt.setColor(QColor("#bf360c"))
    fmt.setBuffer(buffer)
    settings.setFormat(fmt)
    settings.dist = 1.5
    return QgsVectorLayerSimpleLabeling(settings)


def parse_obstacle(meta):
    """Valetudo's obstacle metaData: label "Shoe (85%)", id, image (when it has a
    photo) -> kind, confidence (%), obstacle_id, photo (0/1)."""
    label = str(meta.get("label") or "").strip()
    kind, confidence = label, None
    if label.endswith("%)") and " (" in label:
        kind, _, rest = label.rpartition(" (")
        try:
            confidence = int(float(rest[:-2]))
        except ValueError:
            kind, confidence = label, None
    return {"kind": kind or None, "confidence": confidence, "label": label or None,
            "obstacle_id": meta.get("id"), "photo": 1 if meta.get("image") else 0}


def _changes_renderer():
    """One colour per kind of change, half transparent over the map."""
    kinds = {"wall_added": ("211,47,47", tr("Wall or furniture: new")),
             "wall_removed": ("25,118,210", tr("Wall or furniture: gone")),
             "floor_added": ("67,160,71", tr("Floor: now reached")),
             "floor_removed": ("251,140,0", tr("Floor: no longer reached"))}
    return QgsCategorizedSymbolRenderer("change", [
        QgsRendererCategory(key, _fill(f"{rgb},170", outline=f"{rgb},255", width=0.3), label)
        for key, (rgb, label) in kinds.items()])


def _wall_lines_renderer():
    return QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(
        {"line_color": "#000000", "line_width": "0.5", "capstyle": "round"}))


SENSOR_COLOR = "#6a3d9a"          # a Home Assistant sensor, placed by the user
SENSOR_OFFLINE_COLOR = "#9e9e9e"  # unavailable / unknown state


def _sensors_renderer():
    """Home Assistant sensors: a filled circle, greyed out when unavailable."""
    def dot(color):
        return QgsMarkerSymbol.createSimple({
            "name": "circle", "color": color,
            "outline_color": "white", "outline_width": "0.4", "size": "3.5"})

    return QgsCategorizedSymbolRenderer("available", [
        QgsRendererCategory("yes", dot(SENSOR_COLOR), tr("Sensor")),
        QgsRendererCategory("no", dot(SENSOR_OFFLINE_COLOR), tr("Sensor (offline)")),
    ])


def _sensor_labeling():
    """Label each sensor "Name: value unit" (unit omitted when empty)."""
    settings = QgsPalLayerSettings()
    settings.isExpression = True
    settings.fieldName = (
        "\"label\" || ': ' || \"value\" || "
        "CASE WHEN \"unit\" <> '' THEN ' ' || \"unit\" ELSE '' END"
    )
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.8)
    buffer.setColor(QColor("white"))
    buffer.setOpacity(0.9)
    fmt = QgsTextFormat()
    fmt.setSize(8)
    fmt.setColor(QColor(SENSOR_COLOR))
    font = fmt.font()
    font.setBold(True)
    fmt.setFont(font)
    fmt.setBuffer(buffer)
    settings.setFormat(fmt)
    # Default "around point" placement keeps the text clear of the dot.
    return QgsVectorLayerSimpleLabeling(settings)


# ---------------------------------------------------------------------------
# Reading the Valetudo JSON
# ---------------------------------------------------------------------------

def _runs(layer):
    """Horizontal runs (x, y, length) in pixels."""
    cp = layer.get("compressedPixels")
    if cp is not None:
        for i in range(0, len(cp), 3):
            yield cp[i], cp[i + 1], cp[i + 2]
    else:  # older Valetudo versions
        px = layer.get("pixels", [])
        for i in range(0, len(px), 2):
            yield px[i], px[i + 1], 1


def _layer_geometry(layer, ps):
    rects = [
        QgsGeometry.fromRect(QgsRectangle(x * ps, -(y + 1) * ps, (x + n) * ps, -y * ps))
        for x, y, n in _runs(layer)
    ]
    return QgsGeometry.unaryUnion(rects) if rects else QgsGeometry()


def _signature(map_json):
    """Cheap fingerprint of the map, to know whether rooms must be recomputed."""
    sig = []
    for layer in map_json.get("layers", []):
        meta = layer.get("metaData") or {}
        pixels = layer.get("compressedPixels") or layer.get("pixels") or []
        sig.append((layer.get("type"), meta.get("segmentId"), meta.get("name"), len(pixels)))
    return tuple(sig)


def _memory_layer(geom_type, name, fields):
    lyr = QgsVectorLayer(geom_type, name, "memory")
    lyr.setCrs(QgsCoordinateReferenceSystem())
    lyr.dataProvider().addAttributes(fields)
    lyr.updateFields()
    return lyr


def _set_features(lyr, feats):
    provider = lyr.dataProvider()
    provider.truncate()
    provider.addFeatures(feats)
    lyr.updateExtents()
    lyr.triggerRepaint()


def _area_signature(features):
    return tuple(sorted((f["type"] or "", f.geometry().asWkt(0)) for f in features))


# ---------------------------------------------------------------------------
# Layer manager
# ---------------------------------------------------------------------------

# role -> (geometry, fields, file layer name or None for a live, temporary layer)
ROLES = {
    "sensors": ("Point", [QgsField("entity_id", STR), QgsField("label", STR),
                          QgsField("value", STR), QgsField("unit", STR),
                          QgsField("available", STR)], None),
    "obstacles": ("Point", [QgsField("kind", STR), QgsField("confidence", INT),
                            QgsField("label", STR), QgsField("obstacle_id", STR),
                            QgsField("photo", INT)], None),
    "robot": ("Point", [QgsField("type", STR), QgsField("angle", DBL)], None),
    "lines": ("LineString", [QgsField("type", STR)], None),
    "areas": ("Polygon", [QgsField("type", STR)], "zones"),
    "rooms": ("Polygon", [QgsField("type", STR), QgsField("segment_id", STR),
                          QgsField("name", STR)], "rooms"),
}   # in layer tree order, top to bottom
MAP_FOLDER = "map"
MAP_FILE = "robot_map.gpkg"
SIGNATURE_KEY = "domotiqgis/map_signature"
ENGLISH_NAMES = {"rooms": "Valetudo - map", "areas": "Valetudo - zones",
                 "lines": "Valetudo - lines", "robot": "Valetudo - robot",
                 "sensors": "Valetudo - sensors", "obstacles": "Valetudo - obstacles"}
GEOMETRY = {"Point": Qgis.GeometryType.Point, "LineString": Qgis.GeometryType.Line,
            "Polygon": Qgis.GeometryType.Polygon}


def map_folder():
    return project_folder(MAP_FOLDER)


class ValetudoLayers:
    """The robot's map layers. The map (rooms, walls, floor) and its zones are kept in
    <project folder>/map/robot_map.gpkg once the project is saved, with a copy per
    version of the map (robot_map_<map id>.gpkg, map id as in the history); the robot,
    its path and the sensors are live, temporary layers."""

    def __init__(self, project):
        self.project = project
        self._ids = {}          # role -> layer id (we do NOT keep the objects:
        self._signature = None  # if the user deletes a layer, the Python object dies)
        self._areas = None      # signature of the zones last written
        self.map_id = ""

    # -- access ---------------------------------------------------------------

    def layer(self, role):
        lid = self._ids.get(role)
        return self.project.mapLayer(lid) if lid else None

    def exists(self):
        return all(self.layer(r) for r in ROLES)

    # -- life cycle -----------------------------------------------------------

    def find(self):
        """A project was opened: take over its layers of ours (removing duplicates),
        without creating any. The map saved with it shows even with the robot off."""
        names = layer_names()
        self._ids, self._signature, self._areas = {}, None, None
        for role, (geometry, _fields, _file_name) in ROLES.items():
            lyr = adopt(self.project, f"map/{role}", {names[role], ENGLISH_NAMES[role]},
                        GEOMETRY[geometry])
            if lyr is not None:
                self._ids[role] = lyr.id()
        rooms = self.layer("rooms")
        if rooms is not None and rooms.featureCount():
            self._signature = rooms.customProperty(SIGNATURE_KEY)

    def _ensure(self):
        """Find the layers in the project, create the missing ones.
        Returns True if the map layer had to be created."""
        names = layer_names()
        created = {}
        for role, (geometry, fields, _file_name) in ROLES.items():
            if self.layer(role) is not None:
                continue
            lyr = adopt(self.project, f"map/{role}", {names[role], ENGLISH_NAMES[role]},
                        GEOMETRY[geometry])
            if lyr is None:
                lyr = _memory_layer(geometry, names[role], fields)
                tag(lyr, f"map/{role}")
                created[role] = lyr
            self._ids[role] = lyr.id()
        if created:
            self._add_to_tree(created)
        if "rooms" in created or "areas" in created:
            self._signature = self._areas = None
        elif self._signature is None:   # found again: was it drawn from the same map?
            rooms = self.layer("rooms")
            self._signature = rooms.customProperty(SIGNATURE_KEY) if rooms.featureCount() else None
        return "rooms" in created

    def _add_to_tree(self, created):
        self.project.addMapLayers(list(created.values()), False)
        root = self.project.layerTreeRoot()
        group = root.findGroup(GROUP_NAME) or root.insertGroup(0, GROUP_NAME)
        roles = list(ROLES)
        for role, lyr in created.items():
            lyr.setCrs(QgsCoordinateReferenceSystem())     # undo any default CRS
            # Above the first existing layer of a role further down the list
            index = len(group.children())
            for lower in roles[roles.index(role) + 1:]:
                other = self.layer(lower)
                node = group.findLayer(other.id()) if other is not None else None
                if node is not None:
                    index = group.children().index(node)
                    break
            group.insertLayer(index, lyr)
        renderers = {"sensors": _sensors_renderer, "robot": _points_renderer,
                     "obstacles": _obstacles_renderer,
                     "lines": _lines_renderer, "areas": _areas_renderer,
                     "rooms": lambda: _rooms_renderer([])}
        for role, lyr in created.items():
            lyr.setRenderer(renderers[role]())
        if "sensors" in created:
            created["sensors"].setLabeling(_sensor_labeling())
            created["sensors"].setLabelsEnabled(True)
        if "obstacles" in created:
            created["obstacles"].setLabeling(_obstacle_labeling())
            created["obstacles"].setLabelsEnabled(True)
            add_photo_action(created["obstacles"])
        if "rooms" in created:
            created["rooms"].setLabeling(_room_labeling())
            created["rooms"].setLabelsEnabled(True)

    def remove(self):
        ids = [lid for lid in self._ids.values() if self.project.mapLayer(lid)]
        if ids:
            self.project.removeMapLayers(ids)
        group = self.project.layerTreeRoot().findGroup(GROUP_NAME)
        if group is not None and not group.children():
            group.parent().removeChildNode(group)
        self._ids = {}
        self._signature = self._areas = None

    # -- files ----------------------------------------------------------------

    def persist(self):
        """Once the project is saved: the map and its zones go to map/robot_map.gpkg
        (nothing to do if they are there already). Raises OSError."""
        folder = map_folder()
        if folder is None:
            return False
        moved = False
        for role, (_geometry, _fields, file_name) in ROLES.items():
            if file_name and self.layer(role) is not None:
                moved |= make_permanent(self.layer(role), os.path.join(folder, MAP_FILE),
                                        file_name)
        if moved:
            self._archive()
        return moved

    def _archive(self):
        """A copy of this version of the map, by map id (kept after a remap)."""
        folder = map_folder()
        if folder is None or not self.map_id:
            return
        path = os.path.join(folder, f"robot_map_{self.map_id}.gpkg")
        for role, (_geometry, _fields, file_name) in ROLES.items():
            if file_name and self.layer(role) is not None:
                write_gpkg(self.layer(role), path, file_name)

    # -- update ---------------------------------------------------------------

    def update(self, map_json):
        """Refresh the layers. Returns True if the map layer has just been created.
        Raises OSError when the map file cannot be written (the layers are updated)."""
        created = self._ensure() if not self.exists() else False
        self.map_id = map_fingerprint(map_json) or self.map_id
        changed = False
        sig = hashlib.sha1(repr(_signature(map_json)).encode()).hexdigest()[:16]
        if sig != self._signature:
            self._signature = sig
            self._update_rooms(map_json)
            self.layer("rooms").setCustomProperty(SIGNATURE_KEY, sig)
            changed = True
        changed |= self._update_entities(map_json)
        if map_folder() is not None:
            if not self.persist() and changed:
                self._archive()
            self._snapshot()
        return created

    # -- what the map tells beyond the robot (map_changes.py) -------------------------

    def _snapshot(self):
        """The first map of the day, kept to compare with later."""
        path = map_changes.snapshot_path(map_folder())
        rooms = self.layer("rooms")
        if rooms is not None and rooms.featureCount() and not os.path.exists(path):
            write_gpkg(rooms, path, map_changes.SNAPSHOT_LAYER)

    def _extra_layer(self, role, name, geometry, fields, renderer):
        """A layer of ours outside ROLES (changes, wall lines): found again or created
        at the top of the Valetudo group."""
        lyr = adopt(self.project, role, {name}, GEOMETRY[geometry])
        if lyr is None:
            lyr = _memory_layer(geometry, name, fields)
            tag(lyr, role)
            self.project.addMapLayer(lyr, False)
            root = self.project.layerTreeRoot()
            group = root.findGroup(GROUP_NAME) or root.insertGroup(0, GROUP_NAME)
            group.insertLayer(0, lyr)
        lyr.setName(name)
        lyr.setRenderer(renderer)
        return lyr

    def show_changes(self, snapshot, day_label):
        """The changes since a snapshot, in the "Map changes" layer. Returns how many."""
        rooms = self.layer("rooms")
        earlier = QgsVectorLayer(f"{snapshot}|layername={map_changes.SNAPSHOT_LAYER}",
                                 "snapshot", "ogr")
        if rooms is None or not earlier.isValid():
            raise OSError(snapshot)
        found = map_changes.compare(list(rooms.getFeatures()), list(earlier.getFeatures()))
        lyr = self._extra_layer("map/changes", tr("Map changes since {day}").format(
            day=day_label), "Polygon",
            [QgsField("change", STR), QgsField("area_m2", DBL)], _changes_renderer())
        replace_features(lyr, found)
        lyr.triggerRepaint()
        return len(found)

    def draw_wall_lines(self):
        """The walls as lines, kept in the map's file once the project is saved.
        Returns how many lines."""
        rooms = self.layer("rooms")
        if rooms is None:
            return 0
        lines = map_changes.wall_lines(list(rooms.getFeatures()))
        lyr = self._extra_layer("map/wall_lines", tr("Valetudo - wall lines"), "LineString",
                                [QgsField("length_m", DBL)], _wall_lines_renderer())
        replace_features(lyr, lines)
        folder = map_folder()
        if folder is not None:   # (once in the file, the lines above were written there)
            make_permanent(lyr, os.path.join(folder, MAP_FILE), "wall_lines")
        lyr.triggerRepaint()
        return len(lines)

    def _update_rooms(self, map_json):
        rooms = self.layer("rooms")
        default_ps = map_json.get("pixelSize", 5)
        feats = []
        for layer in map_json.get("layers", []):
            meta = layer.get("metaData") or {}
            geom = _layer_geometry(layer, layer.get("pixelSize", default_ps))
            if not geom.isEmpty():
                feats.append((geom, {
                    "type": layer.get("type"),
                    "segment_id": (str(meta["segmentId"]) if meta.get("segmentId") is not None
                                   else None),
                    "name": meta.get("name"),
                }))
        feats = replace_features(rooms, feats)
        segment_ids = {f["segment_id"] for f in feats if f["segment_id"]}
        rooms.setRenderer(_rooms_renderer(segment_ids))   # one colour per room
        rooms.triggerRepaint()

    def _update_entities(self, map_json):
        """Zones, lines, robot and dock. Returns True if the zones changed."""
        areas, lines, robot = self.layer("areas"), self.layer("lines"), self.layer("robot")
        obstacles = self.layer("obstacles")
        area_f, line_f, point_f, obstacle_f = [], [], [], []
        for ent in map_json.get("entities", []):
            etype = ent.get("type")
            c = ent.get("points", [])
            pts = [v2q(c[i], c[i + 1]) for i in range(0, len(c) - 1, 2)]
            if not pts:
                continue
            # Only genuine point entities go to the points layer. A path may hold a
            # single point (e.g. right after a start): it is skipped, not shown as a point.
            if etype == OBSTACLE:
                obstacle_f.append(new_feature(obstacles, QgsGeometry.fromPointXY(pts[0]),
                                              parse_obstacle(ent.get("metaData") or {})))
            elif etype in POINT_ENTITIES:
                angle = (ent.get("metaData") or {}).get("angle")
                point_f.append(new_feature(robot, QgsGeometry.fromPointXY(pts[0]),
                                           {"type": etype, "angle": angle}))
            elif etype in AREA_ENTITIES:
                if len(pts) >= 3:
                    area_f.append(new_feature(areas, QgsGeometry.fromPolygonXY([pts + [pts[0]]]),
                                              {"type": etype}))
            elif len(pts) >= 2:  # path, predicted_path, virtual_wall...
                line_f.append(new_feature(lines, QgsGeometry.fromPolylineXY(pts),
                                          {"type": etype}))
        # Features are drawn in insertion order: put the robot last, on top of its dock.
        point_f.sort(key=lambda f: f["type"] == "robot_position")
        changed = False
        signature = _area_signature(area_f)
        if self._areas is None:   # found again: compare with what the layer holds
            self._areas = _area_signature(areas.getFeatures())
        if signature != self._areas:   # zones change rarely: no rewrite every 2 s
            self._areas = signature
            _set_features(areas, area_f)
            changed = True
        _set_features(lines, line_f)
        _set_features(robot, point_f)
        _set_features(obstacles, obstacle_f)
        return changed

    def update_sensors(self, items):
        """Refresh the sensors layer from items (each: x, y in cm, entity_id,
        label, value, unit, available). Does nothing if the layers are gone."""
        sensors = self.layer("sensors")
        if sensors is None:
            return
        feats = []
        for it in items:
            geom = QgsGeometry.fromPointXY(v2q(it["x"], it["y"]))
            feats.append((geom, {
                "entity_id": it.get("entity_id", ""), "label": it.get("label", ""),
                "value": "" if it.get("value") is None else str(it.get("value")),
                "unit": it.get("unit", "") or "",
                "available": "yes" if it.get("available") else "no",
            }))
        replace_features(sensors, feats)

    # -- selection --------------------------------------------------------------
