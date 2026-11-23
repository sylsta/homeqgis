"""Frame conversion: Valetudo (cm, Y pointing down) <-> QGIS (cm, Y pointing up).

This is the ONLY place in the plugin that knows about the Y-axis flip.
Georeferencing (an affine transform) would later be added here.
"""

from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY

# The robot's frame as a CRS whose unit is the centimetre, so that QGIS measures
# (measure tool, $length, $area, scale bar) in real units. A transverse Mercator
# centred on 0,0 with scale 1: over a home (a few tens of metres) it is flat and
# exact to well under a millimetre. Before, the layers had no CRS ("unknown units").
ROBOT_PROJ = ("+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +ellps=WGS84 "
              "+units=cm +no_defs")
_ROBOT_CRS = None


def robot_crs():
    """The CRS of every layer of the plugin (and of the project, see plugin.py)."""
    global _ROBOT_CRS
    if _ROBOT_CRS is None or not _ROBOT_CRS.isValid():
        _ROBOT_CRS = QgsCoordinateReferenceSystem.fromProj(ROBOT_PROJ)
    return QgsCoordinateReferenceSystem(_ROBOT_CRS)


def v2q(x, y):
    """Valetudo coordinates -> QGIS point."""
    return QgsPointXY(x, -y)


def q2v(pt):
    """QGIS point -> Valetudo coordinates (integers, in cm)."""
    return int(round(pt.x())), int(round(-pt.y()))
