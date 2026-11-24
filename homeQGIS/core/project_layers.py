"""The plugin's layers in the project: found again when a project is reopened,
and kept in files next to the project once it is saved.

Each layer of ours carries a hidden role tag (custom property). When a project
is opened, the layers of each role are found again and reused instead of new
ones being created; duplicates (the same role twice, e.g. in projects saved
by older versions, whose layers had no tag yet) are removed.

Permanent layers (the map, the Wi-Fi survey) are memory layers until the
project has been saved; then they are written to a GeoPackage in a folder next
to the project file, and the layer is switched to it (style and place in the
layer tree unchanged).
"""

import os

from qgis.core import (QgsFeature, QgsProject,
                       QgsVectorFileWriter, QgsVectorLayer)

from .coords import robot_crs

ROLE_KEY = "domotiqgis/role"


def tag(layer, role):
    layer.setCustomProperty(ROLE_KEY, role)


def role_of(layer):
    return layer.customProperty(ROLE_KEY) or ""


def adopt(project, role, names=(), geometry_type=None):
    """The project's layer for a role: tagged with it or, for projects saved before
    the tags, named as one of names (any language the plugin has used). Extra ones are
    removed from the project. Returns the layer or None."""
    found = []
    for layer in _layers_in_tree_order(project):
        if not isinstance(layer, QgsVectorLayer):
            continue
        if role_of(layer) == role or (not role_of(layer) and layer.name() in names
                                      and (geometry_type is None
                                           or layer.geometryType() == geometry_type)):
            found.append(layer)
    if not found:
        return None
    # Keep the one with data (an old memory layer comes back empty), else the first
    keep = next((l for l in found if l.providerType() != "memory"), None) \
        or next((l for l in found if l.featureCount()), found[0])
    extra = [l.id() for l in found if l is not keep]
    if extra:
        project.removeMapLayers(extra)
    tag(keep, role)
    if not keep.crs().isValid():   # saved before the robot's frame had a CRS (core/coords.py)
        keep.setCrs(robot_crs())
    return keep


def _layers_in_tree_order(project):
    ordered = [node.layer() for node in project.layerTreeRoot().findLayers()
               if node.layer() is not None]
    seen = {layer.id() for layer in ordered}
    return ordered + [l for l in project.mapLayers().values() if l.id() not in seen]


def project_folder(name, project=None):
    """<project home>/<name>, or None while the project has never been saved."""
    project = project or QgsProject.instance()
    if not project.fileName():
        return None
    return os.path.join(project.homePath(), name)


def write_gpkg(layer, path, layer_name):
    """Write a layer's features to a layer of a GeoPackage (created or replaced).
    Raises OSError."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = layer_name
    options.actionOnExistingFile = (
        QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        if os.path.exists(path) else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile)
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsProject.instance().transformContext(), options)
    if result[0] != QgsVectorFileWriter.WriterError.NoError:
        raise OSError(result[1] or f"cannot write {path}")


def make_permanent(layer, path, layer_name):
    """A memory layer: write it to path|layer_name and switch the layer to that file.
    Returns True if switched (False if it was not a memory layer). Raises OSError."""
    if layer is None or layer.providerType() != "memory":
        return False
    if layer.isEditable():
        layer.commitChanges()
    write_gpkg(layer, path, layer_name)
    renderer = layer.renderer().clone() if layer.renderer() else None
    layer.setDataSource(f"{path}|layername={layer_name}", layer.name(), "ogr")
    if not layer.isValid():
        raise OSError(f"cannot open {path} ({layer_name})")
    if renderer is not None:
        layer.setRenderer(renderer)
    layer.setCrs(robot_crs())
    return True


def kept_layer(project, role, name, geometry, fields, folder, file_name, layer_name,
               setup=None):
    """A layer of ours kept in folder/file_name (once the project is saved): found again
    by its role, or created (memory, then the file) at the top of the "Valetudo" group.
    setup(layer) styles a new one. Returns the layer."""
    from qgis.core import Qgis, QgsVectorLayer
    types = {"Point": Qgis.GeometryType.Point, "LineString": Qgis.GeometryType.Line,
             "Polygon": Qgis.GeometryType.Polygon}
    layer = adopt(project, role, {name}, types[geometry])
    path = os.path.join(folder, file_name) if folder is not None else None
    if layer is None and path is not None and os.path.exists(path):
        # Removed from the project but still in its file: reopen it (not overwrite it)
        layer = QgsVectorLayer(f"{path}|layername={layer_name}", name, "ogr")
        if not layer.isValid():
            layer = None
        else:
            layer.setCrs(robot_crs())
            tag(layer, role)
            if setup is not None:
                setup(layer)
            project.addMapLayer(layer, False)
            root = project.layerTreeRoot()
            (root.findGroup("Valetudo") or root.insertGroup(0, "Valetudo")).insertLayer(0, layer)
    if layer is None:
        layer = QgsVectorLayer(geometry, name, "memory")
        layer.setCrs(robot_crs())
        layer.dataProvider().addAttributes(fields)
        layer.updateFields()
        tag(layer, role)
        if setup is not None:
            setup(layer)
        project.addMapLayer(layer, False)
        root = project.layerTreeRoot()
        group = root.findGroup("Valetudo") or root.insertGroup(0, "Valetudo")
        group.insertLayer(0, layer)
    if folder is not None and layer.providerType() == "memory":
        try:
            make_permanent(layer, os.path.join(folder, file_name), layer_name)
        except OSError:
            pass   # stays in memory; tried again next time
    return layer


def replace_features(layer, records):
    """Replace all features: records are (geometry, {field: value}); values are set by
    field name (a GeoPackage layer also has its "fid" column)."""
    fields = layer.fields()
    features = []
    for geometry, values in records:
        feature = QgsFeature(fields)
        feature.setGeometry(geometry)
        for name, value in values.items():
            if fields.indexOf(name) >= 0:
                feature.setAttribute(name, value)
        features.append(feature)
    provider = layer.dataProvider()
    provider.truncate()
    provider.addFeatures(features)
    layer.updateExtents()
    layer.triggerRepaint()
    return features


def new_feature(layer, geometry, values):
    """One feature for layer, its attributes set by name."""
    fields = layer.fields()
    feature = QgsFeature(fields)
    feature.setGeometry(geometry)
    for name, value in values.items():
        if fields.indexOf(name) >= 0:
            feature.setAttribute(name, value)
    return feature
