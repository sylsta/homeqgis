"""The Home section's detail pane, under the device list:

    ┌ Temp sensor · Kitchen ── [6 h][24 h][7 d][10 d] [Compare ▾] [Export ▾] [▶ Map] ┐
    │  (chart: curves, door / motion timelines, 🤖 the robot's cleanings shaded)    │
    │ Temperature: min 19.8 · max 23.9 · mean 21.6 °C                               │
    │ Door: open 4 times, 1 h 20 in all                                             │
    │ 🔋 87 % · about 5 weeks left · 📶 mean 142 (min 98) · dropped out twice       │
    └────────────────────────────────────────────────────────────────────────────────┘

What it shows: the selected device (or entity, or area) over the period, or
the rooms compared (temperature, humidity…). Data from Home Assistant's
history (ha_history); the robot's cleanings from the robot history files.
Export: CSV, or a GeoPackage table next to the project. ▶ Map: the rooms
coloured by the compared value, played in the Temporal Controller.
"""

import csv
import os
import time
from datetime import date, datetime, timedelta

from qgis.PyQt.QtCore import QDateTime, QMetaType, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMenu, QSizePolicy,
                                 QToolButton, QVBoxLayout, QWidget)
from qgis.core import (QgsFeature, QgsField, QgsFillSymbol,
                       QgsProject, QgsProperty, QgsSettings, QgsSymbolLayer, QgsVectorLayer,
                       QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, Qgis)

from ..core.coords import robot_crs
from . import ha_history
from . import ha_home
from ..panel.charts import ChartWidget
from ..history.logic import format_duration
from ..history.store import day_path, history_folder, read_outings
from ..core.i18n import tr
from ..core.project_layers import project_folder, role_of, write_gpkg

KEY_PERIOD = "valetudo/home_period"
ON_STATES = ("on", "open", "playing", "home", "detected")
REPLAY_GROUP = "domotiqgis/home_replay"


def kind_labels():
    return {"temperature": tr("Temperature"), "humidity": tr("Humidity"),
            "carbon_dioxide": "CO₂", "illuminance": tr("Light level"), "power": tr("Power"),
            "pressure": tr("Pressure")}


class DetailPane(QWidget):
    robotDaysRequested = pyqtSignal(list)   # dates: load the robot's history for them

    def __init__(self, client_getter, model_getter, parent=None):
        """client_getter(): the HomeAssistantClient or None; model_getter(): the last
        ha_home.build() model."""
        super().__init__(parent)
        self._client = client_getter
        self._model = model_getter
        self._subject = None       # ("devices", title, devices, area) or ("compare", kind)
        self._request = 0          # number of the last history request (stale answers)
        self._histories = {}       # entity id -> points, for the export
        self._names, self._units = {}, {}
        self._build()

    # -- widgets ----------------------------------------------------------------------

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        head = QHBoxLayout()
        self.lbl_title = QLabel()
        font = self.lbl_title.font()
        font.setBold(True)
        self.lbl_title.setFont(font)
        self.lbl_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head.addWidget(self.lbl_title, 1)
        self.period_buttons = {}
        saved = QgsSettings().value(KEY_PERIOD, "24h", type=str)
        for key, text in (("6h", tr("6 h")), ("24h", tr("24 h")), ("7d", tr("7 d")),
                          ("10d", tr("10 d"))):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setAutoRaise(True)
            button.setChecked(key == saved)
            button.toggled.connect(lambda on, k=key: on and self._on_period(k))
            head.addWidget(button)
            self.period_buttons[key] = button
        if not any(b.isChecked() for b in self.period_buttons.values()):
            self.period_buttons["24h"].setChecked(True)
        self.btn_compare = QToolButton()
        self.btn_compare.setText(tr("Compare"))
        self.btn_compare.setToolTip(tr("The rooms side by side: one curve per room"))
        self.btn_compare.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_compare)
        for kind, label in kind_labels().items():
            menu.addAction(label, lambda k=kind: self.show_compare(k))
        self.btn_compare.setMenu(menu)
        self.btn_export = QToolButton()
        self.btn_export.setText(tr("Export"))
        self.btn_export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_export)
        menu.addAction(tr("CSV file…"), self.export_csv)
        menu.addAction(tr("GeoPackage next to the project"), self.export_gpkg)
        self.btn_export.setMenu(menu)
        self.btn_replay = QToolButton()
        self.btn_replay.setText(tr("▶ Map"))
        self.btn_replay.setToolTip(tr("The rooms coloured by this value over the period, "
                                      "with the robot's outings, in the Temporal Controller"))
        self.btn_replay.clicked.connect(self.replay_on_map)
        for button in (self.btn_compare, self.btn_export, self.btn_replay):
            button.setAutoRaise(True)
            head.addWidget(button)
        layout.addLayout(head)
        self.chart = ChartWidget()
        self.chart.set_message(tr("Select a device, an area or Compare."))
        layout.addWidget(self.chart, 1)
        self.lbl_stats = QLabel()
        self.lbl_stats.setWordWrap(True)
        self.lbl_stats.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.lbl_stats)
        self._update_buttons()

    def _update_buttons(self):
        compare = self._subject is not None and self._subject[0] == "compare"
        self.btn_replay.setVisible(compare)
        self.btn_export.setEnabled(bool(self._histories))

    def _period(self):
        key = next((k for k, b in self.period_buttons.items() if b.isChecked()), "24h")
        return key, ha_history.PERIODS[key]

    def _on_period(self, key):
        QgsSettings().setValue(KEY_PERIOD, key)
        self.reload()

    # -- what to show -------------------------------------------------------------------

    def show_devices(self, title, devices, area_name=""):
        self._subject = ("devices", title, devices, area_name)
        self.chart.set_message(tr("Reading the history…"))
        self.reload()

    def show_compare(self, kind):
        self._subject = ("compare", kind)
        self.reload()

    def clear(self):
        self._subject, self._histories = None, {}
        self.chart.set_message(tr("Select a device, an area or Compare."))
        self.lbl_title.setText("")
        self.lbl_stats.setText("")
        self._update_buttons()

    def reload(self):
        if self._subject is None:
            return
        _key, span = self._period()
        end = time.time()
        start = end - span
        if self._subject[0] == "compare":
            self._load_compare(self._subject[1], start, end)
        else:
            self._load_devices(*self._subject[1:], start, end)
        self._update_buttons()

    def _fetch(self, entity_ids, start, end, done):
        client = self._client()
        if client is None or not entity_ids:
            self.chart.set_message(tr("Nothing to draw."))
            return
        self._request += 1
        number = self._request
        if not self.chart.series and not self.chart.timelines:   # (no flicker on refresh)
            self.chart.set_message(tr("Reading the history…"))

        def ok(answer):
            if number == self._request:   # not a newer request since
                done(ha_history.parse(answer))

        def failed(error):
            if number == self._request:
                self.chart.set_message(tr("History not available: {error}").format(error=error))
        client.get(ha_history.history_path(sorted(set(entity_ids)), start, end), ok, failed,
                   timeout_ms=30000)

    # -- devices ------------------------------------------------------------------------

    def _load_devices(self, title, devices, area_name, start, end):
        self.lbl_title.setText(title)
        entities = [e for d in devices for e in d["main"]]
        health = [e for d in devices for e in d["entities"]
                  if ha_home.is_battery(e) or ha_home.is_link_quality(e)]
        self._names = {e["id"]: e.get("name") or e["id"] for d in devices for e in d["entities"]}
        self._units = {e["id"]: e.get("unit") or "" for d in devices for e in d["entities"]}
        ids = [e["id"] for e in entities + health]
        # the battery's trend needs its 10 days, whatever the period
        long_start = min(start, end - ha_history.PERIODS["10d"])

        def done(histories):
            self._histories = {k: [p for p in v if p[0] >= start] for k, v in histories.items()
                               if k in {e["id"] for e in entities}}
            self._draw_devices(devices, entities, histories, area_name, start, end)
            self._update_buttons()
        self._fetch(ids, long_start if health else start, end, done)

    def _draw_devices(self, devices, entities, histories, area_name, start, end):
        series, timelines, lines = [], [], []
        for entity in entities:
            points = histories.get(entity["id"], [])
            name = entity.get("name") or entity["id"]
            if entity.get("domain") in ("sensor", "number") and ha_history.is_numeric(points):
                values = ha_history.numeric(points)
                series.append({"name": name, "unit": entity.get("unit") or "", "points": values})
                s = ha_history.stats(values, start, end)
                if s:
                    unit = entity.get("unit") or ""
                    lines.append(tr("{name}: min {min} · max {max} · mean {mean} {unit}").format(
                        name=name, min=f"{s['min']:g}", max=f"{s['max']:g}",
                        mean=f"{s['mean']:.1f}", unit=unit).strip())
            elif points:
                periods = ha_history.periods(points, start, end, ON_STATES)
                timelines.append({"name": name, "periods": periods})
                total = sum(b - a for a, b in periods)
                lines.append(tr("{name}: on {count} time(s), {duration} in all").format(
                    name=name, count=len(periods), duration=format_duration(total)))
        marks = [(a, b, tr("🤖 the robot cleaned here")) for a, b in
                 ha_history.robot_cleanings(self._outings(start, end), area_name)]
        if marks:
            lines.append(tr("🤖 The robot cleaned here {n} time(s).").format(n=len(marks)))
        lines += self._health(devices, histories, start, end)
        if not series and not timelines:
            self.chart.set_message(tr("No history for this period."))
        else:
            self.chart.set_data(start, end, series, timelines, marks)
        self.lbl_stats.setText("\n".join(lines))

    def _health(self, devices, histories, start, end):
        lines = []
        for device in devices:
            parts = []
            for entity in device["entities"]:
                points = histories.get(entity["id"], [])
                values = ha_history.numeric(points)
                if ha_home.is_battery(entity) and values:
                    left = ha_history.battery_days_left(values)
                    text = f"🔋 {values[-1][1]:.0f} %"
                    if left is not None:
                        text += " · " + (tr("about {n} week(s) left").format(n=round(left / 7))
                                         if left >= 14 else
                                         tr("about {n} day(s) left").format(n=round(left)))
                    parts.append(text)
                elif ha_home.is_link_quality(entity) and values:
                    s = ha_history.stats(values, start, end)
                    if s:
                        parts.append(tr("📶 mean {mean} (min {min})").format(
                            mean=f"{s['mean']:.0f}", min=f"{s['min']:.0f}"))
            drops = max((ha_history.dropouts([p for p in histories.get(e["id"], [])
                                              if p[0] >= start])
                         for e in device["entities"]), default=0)
            if drops:
                parts.append(tr("unavailable {n} time(s)").format(n=drops))
            if parts:
                prefix = f"{device['name']}: " if len(devices) > 1 else ""
                lines.append(prefix + " · ".join(parts))
        return lines

    @staticmethod
    def _outings(start, end):
        """The robot's outings between start and end (from its history files)."""
        folder = history_folder()
        if folder is None:
            return []
        outings, day = [], date.fromtimestamp(start)
        while day <= date.fromtimestamp(end):
            outings += read_outings(day_path(folder, datetime(day.year, day.month,
                                                              day.day, 12).timestamp()))
            day += timedelta(days=1)
        return [o for o in outings if (o.get("end") or 0) >= start and (o.get("start") or 0) <= end]

    # -- rooms compared -----------------------------------------------------------------

    def _compare_entities(self, kind):
        """{area name: entity} of the first sensor of that kind in each area."""
        model = self._model()
        if not model:
            return {}
        out = {}
        for _key, area, devices in ha_home.group(model, "area"):
            if not area:
                continue
            for device in devices:
                entity = next((e for e in device["entities"] if e.get("domain") == "sensor"
                               and e.get("class") == kind), None)
                if entity is not None:
                    out[area] = entity
                    break
        return out

    def _load_compare(self, kind, start, end):
        label = kind_labels().get(kind, kind)
        self.lbl_title.setText(tr("{kind} by room").format(kind=label))
        per_area = self._compare_entities(kind)
        if not per_area:
            self.chart.set_message(tr("No {kind} sensor in an area.").format(kind=label.lower()))
            self.lbl_stats.setText("")
            self._histories = {}
            return
        self._names = {e["id"]: area for area, e in per_area.items()}
        self._units = {e["id"]: e.get("unit") or "" for e in per_area.values()}

        def done(histories):
            series, lines = [], []
            for area, entity in sorted(per_area.items()):
                values = ha_history.numeric(histories.get(entity["id"], []))
                if not values:
                    continue
                series.append({"name": area, "unit": entity.get("unit") or "", "points": values})
                s = ha_history.stats(values, start, end)
                if s:
                    lines.append(tr("{name}: min {min} · max {max} · mean {mean} {unit}").format(
                        name=area, min=f"{s['min']:g}", max=f"{s['max']:g}",
                        mean=f"{s['mean']:.1f}", unit=entity.get("unit") or "").strip())
            self._histories = {e["id"]: histories.get(e["id"], []) for e in per_area.values()}
            self._compare_series = {area: ha_history.numeric(histories.get(e["id"], []))
                                    for area, e in per_area.items()}
            self._compare_range = (start, end, kind)
            if series:
                self.chart.set_data(start, end, series)
            else:
                self.chart.set_message(tr("No history for this period."))
            self.lbl_stats.setText("\n".join(lines))
            self._update_buttons()
        self._fetch([e["id"] for e in per_area.values()], start, end, done)

    # -- export -------------------------------------------------------------------------

    def export_csv(self):
        if not self._histories:
            return
        name = f"home_{datetime.now():%Y-%m-%d_%H%M}.csv"
        folder = project_folder("history") or os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(self, tr("Export the history"),
                                              os.path.join(folder, name), tr("CSV (*.csv)"))
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["time", "entity_id", "name", "state", "unit"])
                writer.writerows(ha_history.csv_rows(self._histories, self._names, self._units))
        except OSError as exc:
            self.lbl_stats.setText(tr("Not exported: {error}").format(error=exc))
            return
        self.lbl_stats.setText(tr("Exported to {path}").format(path=path))

    def export_gpkg(self):
        folder = project_folder("history")
        if folder is None:
            self.lbl_stats.setText(tr("Save the project first: the GeoPackage goes in its "
                                      "history folder."))
            return
        if not self._histories:
            return
        layer = QgsVectorLayer("None", "home_states", "memory")
        fields = [QgsField("time", QMetaType.Type.QDateTime),
                  QgsField("entity_id", QMetaType.Type.QString),
                  QgsField("name", QMetaType.Type.QString),
                  QgsField("state", QMetaType.Type.QString),
                  QgsField("value", QMetaType.Type.Double),
                  QgsField("unit", QMetaType.Type.QString)]
        layer.dataProvider().addAttributes(fields)
        layer.updateFields()
        features = []
        for entity_id, points in self._histories.items():
            for t, state in points:
                feature = QgsFeature(layer.fields())
                try:
                    value = float(state)
                except ValueError:
                    value = None
                feature.setAttributes([QDateTime.fromMSecsSinceEpoch(int(t * 1000)), entity_id,
                                       self._names.get(entity_id, ""), state, value,
                                       self._units.get(entity_id, "")])
                features.append(feature)
        layer.dataProvider().addFeatures(features)
        path = os.path.join(folder, f"home_{datetime.now():%Y-%m-%d}.gpkg")
        table = f"states_{datetime.now():%H%M%S}"
        try:
            write_gpkg(layer, path, table)
        except OSError as exc:
            self.lbl_stats.setText(tr("Not exported: {error}").format(error=exc))
            return
        self.lbl_stats.setText(tr("Exported to {path} (table {table})").format(
            path=path, table=table))

    # -- the rooms on the map, over time --------------------------------------------------

    def replay_on_map(self):
        """The rooms coloured by the compared value, hour by hour, in the Temporal
        Controller, with the robot's outings of those days."""
        if self._subject is None or self._subject[0] != "compare" \
                or not getattr(self, "_compare_series", None):
            return
        start, end, kind = self._compare_range
        rooms = self._rooms_layer()
        if rooms is None:
            self.lbl_stats.setText(tr("Show the robot's map first (Show on map): the rooms "
                                      "come from it."))
            return
        geometry = {}
        for feature in rooms.getFeatures():
            name = feature["name"]
            if name:
                geometry[str(name).strip().lower()] = feature.geometry()
        step = 3600 if end - start <= 2 * 86400 else 3 * 3600
        layer = QgsVectorLayer("Polygon", tr("{kind} by room").format(
            kind=kind_labels().get(kind, kind)), "memory")
        layer.setCrs(robot_crs())
        layer.dataProvider().addAttributes([
            QgsField("room", QMetaType.Type.QString), QgsField("value", QMetaType.Type.Double),
            QgsField("start", QMetaType.Type.QDateTime),
            QgsField("end", QMetaType.Type.QDateTime)])
        layer.updateFields()
        features, values, matched = [], [], 0
        for area, series in self._compare_series.items():
            shape = geometry.get(area.strip().lower())
            if shape is None or not series:
                continue
            matched += 1
            for t, mean in ha_history.hourly_means(series, start, end, step):
                feature = QgsFeature(layer.fields())
                feature.setGeometry(shape)
                feature.setAttributes([area, round(mean, 2),
                                       QDateTime.fromMSecsSinceEpoch(int(t * 1000)),
                                       QDateTime.fromMSecsSinceEpoch(int((t + step) * 1000))])
                features.append(feature)
                values.append(mean)
        if not features:
            self.lbl_stats.setText(tr("No room of the map is named like a Home Assistant "
                                      "area."))
            return
        layer.dataProvider().addFeatures(features)
        low, high = min(values), max(values)
        if high - low < 1e-9:
            high = low + 1
        symbol = QgsFillSymbol.createSimple({"outline_color": "60,60,60,160",
                                             "outline_width": "0.2"})
        symbol.symbolLayer(0).setDataDefinedProperty(
            QgsSymbolLayer.Property.FillColor, QgsProperty.fromExpression(
                f"set_color_part(ramp_color('RdYlBu', scale_linear(\"value\", {low}, {high}, "
                f"1, 0)), 'alpha', 170)"))
        layer.renderer().setSymbol(symbol)
        labels = QgsPalLayerSettings()
        labels.fieldName = "format_number(\"value\", 1)"
        labels.isExpression = True
        layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
        layer.setLabelsEnabled(True)
        properties = layer.temporalProperties()
        properties.setMode(Qgis.VectorTemporalMode.FeatureDateTimeStartAndEndFromFields)
        properties.setStartField("start")
        properties.setEndField("end")
        properties.setIsActive(True)
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = next((g for g in root.findGroups() if g.customProperty(REPLAY_GROUP)), None)
        if group is None:
            group = root.insertGroup(0, tr("Home replay"))
            group.setCustomProperty(REPLAY_GROUP, True)
        for child in list(group.findLayers()):   # one replay at a time
            project.removeMapLayer(child.layerId())
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        days, day = [], date.fromtimestamp(start)
        while day <= date.fromtimestamp(end):
            days.append(day)
            day += timedelta(days=1)
        self.robotDaysRequested.emit(days)
        from ..history.tab import animate
        animate(start, end)
        self.lbl_stats.setText(tr("{n} room(s) on the map, from {low} to {high}.").format(
            n=matched, low=f"{low:.1f}", high=f"{high:.1f}"))

    @staticmethod
    def _rooms_layer():
        for layer in QgsProject.instance().mapLayers().values():
            if role_of(layer) == "map/rooms" and layer.featureCount():
                return layer
        return None
