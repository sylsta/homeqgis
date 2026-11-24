"""Styles of the history's layers: days since cleaned, trouble spots."""

from qgis.core import (QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsMarkerSymbol,
                       QgsRendererCategory)

from ..core.i18n import tr

# (class, upper bound in days (inclusive), colour): today green … long ago red
DUST_CLASSES = ((0, 0, "26,152,80"), (1, 1, "145,207,96"), (2, 2, "217,239,139"),
                (3, 6, "254,224,139"), (4, 13, "252,141,89"), (5, 10 ** 6, "215,48,39"))
NEVER = 6


def dust_class(days):
    """The colour class of a number of days (None: not cleaned in the window)."""
    if days is None:
        return NEVER
    return next(c for c, upper, _rgb in DUST_CLASSES if days <= upper)


def dust_renderer(window):
    labels = [tr("Today"), tr("Yesterday"), tr("2 days ago"), tr("3 to 6 days"),
              tr("7 to 13 days"), tr("14 days or more")]
    categories = [
        QgsRendererCategory(c, QgsFillSymbol.createSimple(
            {"color": f"{rgb},150", "outline_style": "no"}), label)
        for (c, _upper, rgb), label in zip(DUST_CLASSES, labels)]
    categories.append(QgsRendererCategory(NEVER, QgsFillSymbol.createSimple(
        {"color": "120,0,0,170", "outline_style": "no", "style": "b_diagonal"}),
        tr("Not in {days} days").format(days=window)))
    return QgsCategorizedSymbolRenderer("age", categories)


def trouble_renderer():
    """Semi-transparent circles: where they pile up, the colour darkens."""
    return QgsCategorizedSymbolRenderer("kind", [
        QgsRendererCategory("stuck", QgsMarkerSymbol.createSimple(
            {"name": "circle", "color": "239,108,0,110", "outline_style": "no", "size": "7"}),
            tr("Stuck")),
        QgsRendererCategory("error", QgsMarkerSymbol.createSimple(
            {"name": "cross2", "color": "198,40,40", "outline_color": "198,40,40",
             "outline_width": "0.8", "size": "5"}), tr("Error")),
    ])
