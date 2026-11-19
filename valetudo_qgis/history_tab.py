"""History tab of the panel: browse the robot's recorded outings by day or week,
load them on the map (one layer group per week) and replay one with the
Temporal Controller.

The files are written by history_recorder.py (see history_store.py).
"""

import os
from datetime import date, datetime

from qgis.PyQt.QtCore import QDate, QDateTime, QLocale, Qt, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAction, QComboBox, QDateEdit, QHBoxLayout, QLabel, QSizePolicy, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import (
    Qgis, QgsApplication, QgsCategorizedSymbolRenderer, QgsDateTimeRange, QgsFeatureRequest,
    QgsInterval, QgsLineSymbol, QgsMarkerSymbol, QgsProject, QgsRendererCategory,
    QgsVectorLayer,
)

from .history_logic import format_duration, summarize, week_days, week_key
from .history_store import day_path, history_folder
from .i18n import tr

ROOT_GROUP_KEY = "domotiqgis/history"      # custom property of our layer groups
LAYER_KEY = "domotiqgis/history_layer"     # custom property of our layers: "<day> <name>"
ACTIVITY_COLORS = {"cleaning": "#2e7d32", "go_to": "#1565c0", "returning": "#ef6c00",
                   "manual": "#6a1b9a", "mapping": "#00838f", "other": "#757575"}
REPLAY_SECONDS = 30      # a replay lasts about this long…
REPLAY_FPS = 10
COLUMNS = 6              # start, duration, activities, job, rooms, result
ROLE_OUTING = Qt.ItemDataRole.UserRole


def activity_labels():
    return {"cleaning": tr("Cleaning"), "go_to": tr("Go to"), "returning": tr("Return to dock"),
            "manual": tr("Manual control"), "mapping": tr("Mapping"), "other": tr("Other")}


def job_labels():
    return {"vacuum": tr("Vacuum"), "mop": tr("Mop"), "both": tr("Vacuum and mop"), "": ""}


def result_labels():
    return {"docked": tr("Back on dock"), "stopped": tr("Stopped away"), "error": tr("Error")}


def _value(v):
    """A feature attribute as plain Python (None for NULL, Unix time for a date)."""
    if v is None or (hasattr(v, "isNull") and v.isNull()):
        return None
    if isinstance(v, QDateTime):
        return v.toMSecsSinceEpoch() / 1000
    return v


def read_outings(path):
    """The outings of one day file, oldest first (empty if there is none)."""
    if not os.path.exists(path):
        return []
    layer = QgsVectorLayer(f"{path}|layername=outings", "outings", "ogr")
    if not layer.isValid():
        return []
    names = layer.fields().names()
    outings = []
    for feature in layer.getFeatures():
        record = {name: _value(feature[name]) for name in names}
        record["extent"] = feature.geometry().boundingBox() if feature.hasGeometry() else None
        outings.append(record)
    del layer
    return sorted(outings, key=lambda o: o.get("start") or 0)


def _short_day(day):
    locale = QLocale()
    return "{} {}".format(locale.dayName(day.isoweekday(), QLocale.FormatType.ShortFormat),
                          locale.toString(QDate(day.year, day.month, day.day),
                                          QLocale.FormatType.ShortFormat))


def _clock(t):
    return QLocale().toString(QDateTime.fromMSecsSinceEpoch(int(t * 1000)).time(),
                              QLocale.FormatType.ShortFormat) if t else ""


def _summary_text(outings):
    if not outings:
        return tr("No outing")
    total = summarize(outings)
    parts = [tr("{n} outing(s)").format(n=total["count"]), format_duration(total["duration_s"]),
             f"{total['distance_m']:g} m"]
    if total["area_m2"]:
        parts.append(f"{total['area_m2']:g} m²")
    return " · ".join(parts)


class HistoryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._outings = {}      # outing id -> (record, day)
        self._connected = False
        self._build()
        self.date.setDate(QDate.currentDate())
        self.mode.currentIndexChanged.connect(lambda *_: self.refresh())
        self.date.dateChanged.connect(lambda *_: self.refresh())

    # -- widgets ----------------------------------------------------------------------

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        nav = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem(tr("Day"), "day")
        self.mode.addItem(tr("Week"), "week")
        self.btn_prev = self._tool("◀", tr("Previous day or week"), lambda: self._step(-1))
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.btn_next = self._tool("▶", tr("Next day or week"), lambda: self._step(1))
        self.btn_today = self._tool(tr("Today"), tr("Back to today"),
                                    lambda: self.date.setDate(QDate.currentDate()))
        for widget in (self.mode, self.btn_prev, self.date, self.btn_next, self.btn_today):
            nav.addWidget(widget)
        nav.addStretch(1)
        layout.addLayout(nav)

        self.lbl_summary = QLabel()
        layout.addWidget(self.lbl_summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Start"), tr("Duration"), tr("Activities"), tr("Job"),
                                   tr("Rooms"), tr("Result")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.load(zoom=True))
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.btn_load = self._tool(tr("Load on map"),
                                   tr("Add the day (or the week) to the map, in a group per "
                                      "week; the points layer starts hidden"),
                                   lambda: self.load(zoom=True), "/mActionAddLayer.svg")
        self.btn_replay = self._tool(tr("Replay"),
                                     tr("Replay the selected outing (or the whole day) with "
                                        "QGIS's Temporal Controller"),
                                     self.replay, "/mIndicatorTemporal.svg")
        self.btn_folder = self._tool(tr("Open folder"), tr("Open the history folder"),
                                     self._open_folder, "/mActionFileOpen.svg")
        for button in (self.btn_load, self.btn_replay, self.btn_folder):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.lbl_info = QLabel()
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

    def _tool(self, text, tip, slot, theme_icon=None):
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tip)
        if theme_icon:
            button.setIcon(QgsApplication.getThemeIcon(theme_icon))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.clicked.connect(slot)
        return button

    # -- life cycle --------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if not self._connected:
            QgsProject.instance().homePathChanged.connect(self.refresh)
            self._connected = True
        self.refresh()

    def shutdown(self):
        if self._connected:
            try:
                QgsProject.instance().homePathChanged.disconnect(self.refresh)
            except (TypeError, RuntimeError):
                pass
            self._connected = False

    def written(self, path):
        """The recorder wrote a file: refresh the list if it shows that day, and the
        layers already on the map."""
        for layer in self._our_layers():
            if layer.source().split("|")[0] == path:
                layer.reload()
                layer.triggerRepaint()
        if self.isVisible() and path in [day_path(self._folder() or "", self._t(d))
                                         for d in self._days()]:
            self.refresh()

    # -- browsing ----------------------------------------------------------------------

    def _selected_day(self):
        d = self.date.date()
        return date(d.year(), d.month(), d.day())

    def _days(self):
        day = self._selected_day()
        return week_days(day) if self.mode.currentData() == "week" else [day]

    @staticmethod
    def _t(day):
        return datetime(day.year, day.month, day.day, 12).timestamp()

    @staticmethod
    def _folder():
        return history_folder()

    def _step(self, sign):
        self.date.setDate(self.date.date().addDays(sign * (7 if self.mode.currentData() == "week"
                                                           else 1)))

    def refresh(self, *_):
        self.tree.clear()
        self._outings = {}
        folder = self._folder()
        if folder is None:
            self.lbl_summary.setText("")
            self.lbl_info.setText(tr("Save the project: the robot's history is kept in a "
                                     "history folder next to the project file."))
            self._update_buttons()
            return
        week = self.mode.currentData() == "week"
        self.tree.setRootIsDecorated(week)
        everything = []
        for day in self._days():
            outings = read_outings(day_path(folder, self._t(day)))
            everything += outings
            parent = None
            if week:
                if not outings:
                    continue
                parent = QTreeWidgetItem([f"{_short_day(day)} — {_summary_text(outings)}"])
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                self.tree.addTopLevelItem(parent)
                parent.setFirstColumnSpanned(True)
            for outing in outings:
                item = self._outing_item(outing)
                self._outings[outing["outing"]] = (outing, day)
                (parent.addChild(item) if parent is not None else self.tree.addTopLevelItem(item))
            if parent is not None:
                parent.setExpanded(True)
        self.lbl_summary.setText(_summary_text(everything))
        self.lbl_info.setText("" if everything or os.path.isdir(folder)
                              else tr("Nothing recorded yet in {folder}.").format(folder=folder))
        for column in range(COLUMNS):
            self.tree.resizeColumnToContents(column)
        self._update_buttons()

    def _outing_item(self, outing):
        activities = activity_labels()
        names = [activities.get(a, a) for a in (outing.get("activities") or "").split(",") if a]
        start = _clock(outing.get("start"))
        if outing.get("scheduled"):
            start += " ⏰"
        area = outing.get("area_m2")
        duration = format_duration(outing.get("duration_s"))
        item = QTreeWidgetItem([start, duration, ", ".join(names),
                                job_labels().get(outing.get("job_type") or "", ""),
                                outing.get("rooms") or "",
                                result_labels().get(outing.get("result"), outing.get("result") or "")])
        item.setData(0, ROLE_OUTING, outing["outing"])
        tip = [tr("{start} – {end}").format(start=_clock(outing.get("start")),
                                            end=_clock(outing.get("end"))),
               tr("Distance: {d:g} m").format(d=outing.get("distance_m") or 0)]
        if area:
            tip.append(tr("Area cleaned: {a:g} m²").format(a=area))
        tip.append(tr("Started by a schedule") if outing.get("scheduled")
                   else tr("Started by hand or from QGIS"))
        for column in range(COLUMNS):
            item.setToolTip(column, "\n".join(tip))
        if outing.get("result") == "error":
            item.setForeground(5, QColor("#c62828"))
        return item

    def _selected_outing(self):
        items = self.tree.selectedItems()
        outing_id = items[0].data(0, ROLE_OUTING) if items else None
        return self._outings.get(outing_id) if outing_id else None

    def _update_buttons(self):
        has = bool(self._outings)
        self.btn_load.setEnabled(has)
        self.btn_replay.setEnabled(has)
        self.btn_folder.setEnabled(self._folder() is not None)

    def _on_selection(self):
        selected = self._selected_outing()
        if selected is None:
            return
        outing, day = selected
        layer = self._find_layer(day, "outings")
        if layer is not None:
            self._select_and_zoom(layer, outing["outing"])

    # -- layers ------------------------------------------------------------------------

    def _our_layers(self):
        return [layer for layer in QgsProject.instance().mapLayers().values()
                if layer.customProperty(LAYER_KEY)]

    def _find_layer(self, day, name):
        key = f"{day.isoformat()} {name}"
        for layer in self._our_layers():
            if layer.customProperty(LAYER_KEY) == key:
                return layer
        return None

    def _day_group(self, day):
        root = QgsProject.instance().layerTreeRoot()
        top = next((g for g in root.findGroups() if g.customProperty(ROOT_GROUP_KEY) == "root"),
                   None)
        if top is None:
            top = root.insertGroup(0, tr("Robot history"))
            top.setCustomProperty(ROOT_GROUP_KEY, "root")
        year, number = week_key(day)
        week_id = f"{year}-W{number:02d}"
        week = next((g for g in top.findGroups() if g.customProperty(ROOT_GROUP_KEY) == week_id),
                    None)
        if week is None:
            week = top.addGroup(tr("Week {n} · {year}").format(n=number, year=year))
            week.setCustomProperty(ROOT_GROUP_KEY, week_id)
        group = next((g for g in week.findGroups()
                      if g.customProperty(ROOT_GROUP_KEY) == day.isoformat()), None)
        if group is None:
            # Days in order within the week
            later = [i for i, child in enumerate(week.children())
                     if (child.customProperty(ROOT_GROUP_KEY) or "") > day.isoformat()]
            group = week.insertGroup(later[0] if later else len(week.children()), _short_day(day))
            group.setCustomProperty(ROOT_GROUP_KEY, day.isoformat())
        return group

    def _load_day(self, day):
        """Add (or reload) a day's three layers. Returns {name: layer}, empty if no file."""
        folder = self._folder()
        path = day_path(folder, self._t(day)) if folder else None
        if not path or not os.path.exists(path):
            return {}
        project = QgsProject.instance()
        layers = {}
        group = None
        for name, title in (("points", tr("Points")), ("segments", tr("Segments")),
                            ("outings", tr("Outings"))):   # top to bottom
            layer = self._find_layer(day, name)
            if layer is not None:
                layer.reload()
                layers[name] = layer
                continue
            layer = QgsVectorLayer(f"{path}|layername={name}",
                                   f"{title} {day:%d/%m}", "ogr")
            if not layer.isValid():
                continue
            layer.setCustomProperty(LAYER_KEY, f"{day.isoformat()} {name}")
            _style(layer, name)
            project.addMapLayer(layer, False)
            group = group or self._day_group(day)
            node = group.addLayer(layer)
            if name == "points":
                node.setItemVisibilityChecked(False)
            layers[name] = layer
        return layers

    def load(self, zoom=False):
        selected = self._selected_outing()
        days = [selected[1]] if selected and self.mode.currentData() == "day" else self._days()
        loaded = {}
        for day in days:
            layers = self._load_day(day)
            if layers:
                loaded[day] = layers
        if not loaded:
            return {}
        if zoom:
            if selected and selected[1] in loaded:
                self._select_and_zoom(loaded[selected[1]]["outings"], selected[0]["outing"])
            else:
                self._zoom_to([layers["outings"] for layers in loaded.values()
                               if "outings" in layers])
        return loaded

    @staticmethod
    def _canvas():
        from qgis.utils import iface
        return iface.mapCanvas() if iface is not None else None

    def _zoom_to(self, layers):
        canvas = self._canvas()
        extent = None
        for layer in layers:
            layer.updateExtents()
            if not layer.featureCount():
                continue
            if extent is None:
                extent = layer.extent()
            else:
                extent.combineExtentWith(layer.extent())
        if canvas is not None and extent is not None and not extent.isEmpty():
            canvas.setExtent(extent.buffered(max(extent.width(), extent.height()) * 0.1 + 50))
            canvas.refresh()

    def _select_and_zoom(self, layer, outing_id):
        request = QgsFeatureRequest().setFilterExpression(
            "\"outing\" = '{}'".format(str(outing_id).replace("'", "''")))
        ids = [f.id() for f in layer.getFeatures(request)]
        layer.selectByIds(ids)
        canvas = self._canvas()
        if canvas is not None and ids:
            box = layer.boundingBoxOfSelected()
            if not box.isEmpty():
                canvas.setExtent(box.buffered(max(box.width(), box.height()) * 0.15 + 50))
                canvas.refresh()

    # -- replay ------------------------------------------------------------------------

    def replay(self):
        selected = self._selected_outing()
        if selected is not None:
            outing, day = selected
            start, end = outing.get("start"), outing.get("end")
        else:   # the whole day (in a week: the first day with outings)
            days = sorted({d for _r, d in self._outings.values()})
            if not days:
                return
            day = days[0]
            records = [r for r, d in self._outings.values() if d == day]
            start = min(r.get("start") or 0 for r in records)
            end = max(r.get("end") or 0 for r in records)
        if not start or not end or end <= start:
            return
        layers = self._load_day(day)
        points = layers.get("points")
        if points is None:
            return
        properties = points.temporalProperties()
        properties.setMode(Qgis.VectorTemporalMode.FeatureDateTimeInstantFromField)
        properties.setStartField("time")
        properties.setAccumulateFeatures(True)   # the trail so far
        properties.setIsActive(True)
        root = QgsProject.instance().layerTreeRoot()
        for name, layer in layers.items():
            node = root.findLayer(layer.id())
            if node is not None:
                node.setItemVisibilityChecked(name == "points")
        if selected is not None:
            self._select_and_zoom(layers["outings"], selected[0]["outing"])
        else:
            self._zoom_to([layers["outings"]])
        self._start_animation(start, end)
        self.lbl_info.setText(tr("Replay in the Temporal Controller: the points appear as the "
                                 "robot went; the segments and outings layers of the day are "
                                 "hidden meanwhile."))

    def _start_animation(self, start, end):
        from qgis.utils import iface
        if iface is None:
            return
        action = iface.mainWindow().findChild(QAction, "mActionTemporalController")
        if action is not None and not action.isChecked():
            action.trigger()   # shows the Temporal Controller panel
        navigation = iface.mapCanvas().temporalController()
        if not hasattr(navigation, "setTemporalExtents"):
            return
        step_s = max(2, round((end - start) / (REPLAY_SECONDS * REPLAY_FPS)))
        navigation.setNavigationMode(Qgis.TemporalNavigationMode.Animated)
        navigation.setTemporalExtents(QgsDateTimeRange(
            QDateTime.fromMSecsSinceEpoch(int(start * 1000)),
            QDateTime.fromMSecsSinceEpoch(int((end + step_s) * 1000))))
        navigation.setFrameDuration(QgsInterval(step_s))
        navigation.setFramesPerSecond(REPLAY_FPS)
        navigation.setCurrentFrameNumber(0)
        navigation.playForward()

    def _open_folder(self):
        folder = self._folder()
        if folder is None:
            return
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def _style(layer, name):
    """Colours by activity (segments, points); outings as a light halo underneath."""
    if name == "outings":
        symbol = QgsLineSymbol.createSimple({"line_color": "255,193,7,110", "line_width": "2.4",
                                             "capstyle": "round", "joinstyle": "round"})
        layer.renderer().setSymbol(symbol)
        return
    labels = activity_labels()
    categories = []
    for activity, color in ACTIVITY_COLORS.items():
        if name == "segments":
            symbol = QgsLineSymbol.createSimple({"line_color": color, "line_width": "0.8",
                                                 "capstyle": "round", "joinstyle": "round"})
        else:
            symbol = QgsMarkerSymbol.createSimple({"name": "circle", "color": color,
                                                   "outline_style": "no", "size": "1.4"})
        categories.append(QgsRendererCategory(activity, symbol, labels[activity]))
    layer.setRenderer(QgsCategorizedSymbolRenderer("activity", categories))
