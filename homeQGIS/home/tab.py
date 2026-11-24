"""The panel's Home tab: Home Assistant's devices, by area or by integration.

    🔍 [filter…]   Group by [Area ▾]   ☐ Problems only   ☐ Other entities   ⟳
    ▾ Kitchen                       21.4 °C · 58 % · 1 open
        🌡 Temp sensor              21.4 °C · 58 %    🔋 87 %  📶 142
        🚪 Door                     closed            🔋 92 %
        💡 Ceiling light            on (80 %)                         [⏻]
    ▸ Living room (4)
    ▸ No area (2)

Read with one template request (ha_home.TEMPLATE) every 15 s while the tab is
shown; lights, plugs and switches toggle with ⏻ (services/<domain>/toggle).
"""

import time

from qgis.PyQt.QtCore import QSize, QTimer, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                                 QLineEdit, QSplitter, QToolButton, QTreeWidget,
                                 QTreeWidgetItem, QVBoxLayout, QWidget)
from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsSettings

from . import ha_history
from . import ha_home
from ..panel.charts import color, sparkline_pixmap
from .ha_client import UNAUTHORISED, HomeAssistantClient
from .detail import ON_STATES, DetailPane
from ..core.i18n import tr
from ..core.settings import load_settings, secret

REFRESH_MS = 15_000
BUSY_GIVE_UP_S = 45      # an answer not back after this: asked again
DETAIL_EVERY_S = 60      # the detail pane's graphs: read again every minute
KEY_GROUP_BY = "valetudo/home_group_by"
KEY_PROBLEMS_ONLY = "valetudo/home_problems_only"
KEY_VIRTUAL = "valetudo/home_virtual"
KEY_SPLITTER = "valetudo/home_splitter"
SPARK_EVERY_S = 300      # the list's 24 h graphs: read again every 5 min
BATTERY_EVERY_S = 3600   # the batteries' 10 days (their trend): every hour
SOON_DAYS = 14           # a battery to change within this: listed by the ⚠
ROLE_KEY = Qt.ItemDataRole.UserRole
COL_NAME, COL_STATE, COL_SPARK, COL_BATTERY, COL_LQI, COL_ACTION = range(6)
FADED, WARN = QColor("#9e9e9e"), QColor("#ef6c00")


def _state_words():
    return {"open": tr("open"), "closed": tr("closed"), "motion": tr("motion"),
            "no motion": tr("no motion"), "occupied": tr("occupied"), "clear": tr("clear"),
            "home": tr("home"), "away": tr("away"), "wet": tr("wet"), "dry": tr("dry"),
            "smoke!": tr("smoke!"), "gas!": tr("gas!"), "low": tr("low"),
            "normal": tr("normal"), "problem": tr("problem"), "OK": "OK"}


class HomeTab(QWidget):
    problemsChanged = pyqtSignal(int, int, int)   # unavailable, low batteries, soon empty
    robotDaysRequested = pyqtSignal(list)         # see DetailPane

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None
        self._for = None          # (url, token key) the client was made for
        self._token = None
        self._data = None         # the last answer of the template
        self._busy = False
        self._busy_since = 0.0
        self._updated_at = ""
        self._detail_at = 0.0
        self._model = None
        self._spark, self._spark_at = {}, 0.0        # entity id -> 24 h of points
        self._batteries, self._battery_at = {}, 0.0  # battery entity id -> 10 days
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._build()

    # -- widgets ----------------------------------------------------------------------

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.edit_filter = QLineEdit()
        self.edit_filter.setPlaceholderText(tr("Filter: name, model, area…"))
        self.edit_filter.setClearButtonEnabled(True)
        self.edit_filter.textChanged.connect(lambda *_: self._render())
        self.cmb_group = QComboBox()
        self.cmb_group.addItem(tr("By area"), "area")
        self.cmb_group.addItem(tr("By integration"), "integration")
        s = QgsSettings()
        self.cmb_group.setCurrentIndex(max(0, self.cmb_group.findData(
            s.value(KEY_GROUP_BY, "area", type=str))))
        self.cmb_group.currentIndexChanged.connect(self._on_option)
        self.btn_refresh = QToolButton()
        self.btn_refresh.setIcon(QgsApplication.getThemeIcon("/mActionRefresh.svg"))
        self.btn_refresh.setToolTip(tr("Read Home Assistant again now"))
        self.btn_refresh.setAutoRaise(True)
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.edit_filter, 1)
        row.addWidget(self.cmb_group)
        row.addWidget(self.btn_refresh)
        layout.addLayout(row)
        options = QHBoxLayout()
        self.chk_problems = QCheckBox(tr("Problems only"))
        self.chk_problems.setToolTip(tr("Unavailable devices, low batteries and batteries to "
                                        "change within two weeks"))
        self.chk_problems.setChecked(s.value(KEY_PROBLEMS_ONLY, False, type=bool))
        self.chk_virtual = QCheckBox(tr("Other entities"))
        self.chk_virtual.setToolTip(tr("Also Home Assistant's own entities, without a device: "
                                       "sun, weather, automations, scripts, helpers…"))
        self.chk_virtual.setChecked(s.value(KEY_VIRTUAL, False, type=bool))
        for box in (self.chk_problems, self.chk_virtual):
            box.toggled.connect(self._on_option)
            options.addWidget(box)
        options.addStretch(1)
        layout.addLayout(options)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels([tr("Device"), tr("State"), tr("24 h"), "🔋", "📶", ""])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(80, 16))   # the 24 h graphs
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for column in (COL_STATE, COL_SPARK, COL_BATTERY, COL_LQI, COL_ACTION):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        # The list above, the selected device's graphs below
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.tree)
        self.detail = DetailPane(self._ha, lambda: self._model, self)
        self.detail.robotDaysRequested.connect(self.robotDaysRequested)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        state = QgsSettings().value(KEY_SPLITTER)
        if state is not None:
            self.splitter.restoreState(state)
        self.splitter.splitterMoved.connect(
            lambda *_: QgsSettings().setValue(KEY_SPLITTER, self.splitter.saveState()))
        layout.addWidget(self.splitter, 1)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

    def _on_option(self, *_):
        s = QgsSettings()
        s.setValue(KEY_GROUP_BY, self.cmb_group.currentData())
        s.setValue(KEY_PROBLEMS_ONLY, self.chk_problems.isChecked())
        s.setValue(KEY_VIRTUAL, self.chk_virtual.isChecked())
        self._render()

    # -- life cycle -------------------------------------------------------------------

    def set_active(self, active):
        """Read Home Assistant while the tab is shown (and the panel visible)."""
        if active:
            if not self._timer.isActive():
                self._timer.start()
                self.refresh()
        else:
            self._timer.stop()

    def settings_changed(self):
        self._token, self._for, self._data, self._model = None, None, None, None
        self._spark, self._spark_at, self._batteries, self._battery_at = {}, 0.0, {}, 0.0
        self.tree.clear()
        self.detail.clear()
        if self._timer.isActive():
            self.refresh()

    def shutdown(self):
        self._timer.stop()
        if self._client is not None:
            self._client.close()

    # -- reading ----------------------------------------------------------------------

    def _ha(self):
        cfg = load_settings()
        url, key = cfg["ha_url"], cfg["ha_token_key"]
        if not url:
            return None
        if self._client is None or self._for != (url, key):
            if self._client is not None:
                self._client.close()
            if self._token is None:
                self._token = secret(key).strip()   # may ask for the master password, once
            self._client = HomeAssistantClient(url, self._token, self)
            self._for = (url, key)
            self._busy = False
        return self._client

    def refresh(self, *_):
        client = self._ha()
        if client is None:
            self.tree.clear()
            self.lbl_status.setText(tr("Add a Home Assistant server in the settings "
                                       "(Servers tab) to see your devices here."))
            return
        if not client.token:
            self.lbl_status.setText(tr("Home Assistant needs an access token to list its "
                                       "devices: add one in the settings (Servers tab)."))
            return
        if self._busy and time.monotonic() - self._busy_since < BUSY_GIVE_UP_S:
            return   # the previous answer is still awaited (given up after a while)
        self._busy, self._busy_since = True, time.monotonic()
        if self._data is None:
            self.lbl_status.setText(tr("Reading Home Assistant…"))

        def ok(data):
            self._busy = False
            if not isinstance(data, dict):
                self.lbl_status.setText(tr("Unexpected answer from Home Assistant."))
                return
            self._data = data
            self._updated_at = time.strftime("%H:%M:%S")
            try:
                self._render()
                self._read_histories()
                if time.monotonic() - self._detail_at >= DETAIL_EVERY_S:
                    self._detail_at = time.monotonic()
                    self.detail.reload()   # the selected device's graphs too
            except Exception as exc:   # shown, rather than refreshing no more silently
                import traceback
                QgsMessageLog.logMessage(traceback.format_exc(), "HomeQGIS",
                                         Qgis.MessageLevel.Warning)
                self.lbl_status.setText(tr("Display error: {error} (details in the "
                                           "HomeQGIS log)").format(error=exc))

        def failed(error):
            self._busy = False
            self.lbl_status.setText(tr("Home Assistant: {error}").format(
                error=tr("the access token was refused") if error == UNAUTHORISED else error))

        client.post("/template", {"template": ha_home.TEMPLATE}, ok, failed, timeout_ms=15000)

    def _read_histories(self):
        """The 24 h graphs of the list (every 5 min) and the batteries' 10 days (every
        hour, for their trend), each with one history request."""
        client, model, now = self._client, self._model, time.time()
        if client is None or model is None:
            return
        if now - self._spark_at >= SPARK_EVERY_S:
            ids = [d["main"][0]["id"] for d in model["devices"] if d["main"]]
            if ids:
                self._spark_at = now

                def sparks(answer):
                    self._spark = ha_history.parse(answer)
                    self._render()
                client.get(ha_history.history_path(ids, now - 86400, now), sparks,
                           timeout_ms=30000)
        if now - self._battery_at >= BATTERY_EVERY_S:
            ids = [e["id"] for d in model["devices"] for e in d["entities"]
                   if ha_home.is_battery(e)]
            if ids:
                self._battery_at = now

                def batteries(answer):
                    self._batteries = {k: ha_history.numeric(v)
                                       for k, v in ha_history.parse(answer).items()}
                    self._render()
                client.get(ha_history.history_path(ids, now - 10 * 86400, now), batteries,
                           timeout_ms=30000)

    def _battery_days_left(self, device):
        entity = next((e for e in device["entities"] if ha_home.is_battery(e)), None)
        series = self._batteries.get(entity["id"]) if entity else None
        return ha_history.battery_days_left(series) if series else None

    def _spark_for(self, entity):
        points = self._spark.get(entity["id"])
        if not points:
            return None
        now = time.time()
        if ha_history.is_numeric(points):
            values = ha_history.sample(ha_history.numeric(points), now - 86400, now, 40)
            return sparkline_pixmap(values, line_color=color(0).name())
        buckets = 48
        on = ha_history.periods(points, now - 86400, now, ON_STATES)
        width = 86400 / buckets
        values = [any(a < now - 86400 + (i + 1) * width and b > now - 86400 + i * width
                      for a, b in on) for i in range(buckets)]
        return sparkline_pixmap(values, line_color=color(2).name(), binary=True)

    def _on_selection(self):
        self._detail_at = time.monotonic()
        items = self.tree.selectedItems()
        key = items[0].data(COL_NAME, ROLE_KEY) if items else None
        model = self._model
        if not key or model is None:
            return
        kind, _, ident = str(key).partition(":")
        if kind == "device":
            device = next((d for d in model["devices"] if d["id"] == ident), None)
            if device is not None:
                title = " · ".join(p for p in (device["name"], device["area_name"]) if p)
                self.detail.show_devices(title, [device], device["area_name"])
        elif kind == "entity":
            for device in model["devices"]:
                entity = next((e for e in device["entities"] if e.get("id") == ident), None)
                if entity is not None:
                    single = dict(device, main=[entity])
                    self.detail.show_devices(entity.get("name") or ident, [single],
                                             device["area_name"])
                    return
        elif kind == "group" and self.cmb_group.currentData() == "area" and ident != "None":
            devices = [d for d in model["devices"] if d["area"] == ident]
            name = model["areas"].get(ident, ident)
            self.detail.show_devices(name, devices, name)

    # -- display ----------------------------------------------------------------------

    def _render(self):
        if self._data is None:
            return
        model = ha_home.build(self._data, self.chk_virtual.isChecked())
        for device in model["devices"]:   # battery to change soon: a problem too
            left = self._battery_days_left(device)
            device["days_left"] = left
            if left is not None and left < SOON_DAYS and "low_battery" not in device["problems"]:
                device["problems"].append("battery_soon")
        self._model = model
        words = _state_words()
        expanded = self._expanded()
        first_time = not expanded and self.tree.topLevelItemCount() == 0
        selected = [i.data(COL_NAME, ROLE_KEY) for i in self.tree.selectedItems()]
        scroll = self.tree.verticalScrollBar().value()
        self.tree.blockSignals(True)   # (no detail reload for the same selection)
        self.tree.clear()
        text, problems_only = self.edit_filter.text(), self.chk_problems.isChecked()
        shown = 0
        for key, name, devices in ha_home.group(model, self.cmb_group.currentData()):
            visible = [d for d in devices if ha_home.matches(d, text)
                       and (not problems_only or d["problems"])]
            if not visible:
                continue
            group_key = f"group:{key}"
            label = name or (tr("No area") if self.cmb_group.currentData() == "area"
                             else tr("Other"))
            group = QTreeWidgetItem([f"{label} ({len(visible)})", ha_home.area_summary(
                visible, {"open": tr("{n} open"), "motion": tr("motion")})])
            group.setData(COL_NAME, ROLE_KEY, group_key)
            font = QFont(group.font(COL_NAME))
            font.setBold(True)
            group.setFont(COL_NAME, font)
            self.tree.addTopLevelItem(group)
            group.setFirstColumnSpanned(False)
            for device in visible:
                self._add_device(group, device, words, expanded)
                shown += 1
            group.setExpanded(first_time or group_key in expanded)
        if model["loose"] and not problems_only:
            loose = [e for e in model["loose"] if not text or text.lower() in
                     (e.get("id", "") + " " + (e.get("name") or "")).lower()]
            if loose:
                group = QTreeWidgetItem([f"{tr('Other entities')} ({len(loose)})"])
                group.setData(COL_NAME, ROLE_KEY, "group:loose")
                self.tree.addTopLevelItem(group)
                for entity in loose:
                    self._add_entity(group, entity, words)
                group.setExpanded("group:loose" in expanded)
        if selected:
            self._select(selected[0])
        self.tree.blockSignals(False)
        self.tree.verticalScrollBar().setValue(scroll)
        unavailable = sum(1 for d in model["devices"] if "unavailable" in d["problems"])
        low = sum(1 for d in model["devices"] if "low_battery" in d["problems"])
        soon = sum(1 for d in model["devices"] if "battery_soon" in d["problems"])
        self.problemsChanged.emit(unavailable, low, soon)
        parts = [tr("{n} device(s)").format(n=len(model["devices"]))]
        if unavailable:
            parts.append(tr("{n} unavailable").format(n=unavailable))
        if low:
            parts.append(tr("{n} low battery").format(n=low))
        if shown != len(model["devices"]):
            parts.append(tr("{n} shown").format(n=shown))
        if self._updated_at:
            parts.append(tr("updated at {time}").format(time=self._updated_at))
        self.lbl_status.setText(" · ".join(parts))

    def _select(self, key):
        """Select the item with this key again (after the list was rebuilt)."""
        def walk(item):
            if item.data(COL_NAME, ROLE_KEY) == key:
                item.setSelected(True)
                return True
            return any(walk(item.child(i)) for i in range(item.childCount()))
        for i in range(self.tree.topLevelItemCount()):
            if walk(self.tree.topLevelItem(i)):
                return

    def _expanded(self):
        keys = set()

        def walk(item):
            if item.isExpanded():
                keys.add(item.data(COL_NAME, ROLE_KEY))
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return keys

    def _add_device(self, parent, device, words, expanded):
        main = device["main"]
        symbol = ha_home.icon_for(main[0]) if main else "•"
        values = " · ".join(ha_home.value_text(e, words) for e in main)
        battery = f"{device['battery']:.0f} %" if device["battery"] is not None else ""
        left = device.get("days_left")
        if battery and left is not None:
            battery += f" (~{round(left / 7)} w)" if left >= 14 else f" (~{round(left)} d)"
        item = QTreeWidgetItem(parent, [
            f"{symbol} {device['name']}", values, "", battery,
            f"{device['lqi']:.0f}" if device["lqi"] is not None else ""])
        if main:
            spark = self._spark_for(main[0])
            if spark is not None:
                item.setData(COL_SPARK, Qt.ItemDataRole.DecorationRole, spark)
        if left is not None:
            item.setToolTip(COL_BATTERY, tr("About {n} day(s) left, from the last 10 days")
                            .format(n=round(left)))
        item.setData(COL_NAME, ROLE_KEY, f"device:{device['id']}")
        tip = " · ".join(p for p in (device["maker"], device["model"],
                                     ha_home.integration_name(device["integration"])) if p)
        item.setToolTip(COL_NAME, tip)
        item.setToolTip(COL_LQI, tr("Zigbee link quality (0–255)"))
        if not device["available"]:
            for column in range(5):
                item.setForeground(column, FADED)
            item.setToolTip(COL_STATE, tr("Unavailable"))
        if "low_battery" in device["problems"] or "battery_soon" in device["problems"]:
            item.setForeground(COL_BATTERY, WARN)
        if device["toggles"]:
            self._toggle_button(item, device["toggles"][0])
        for entity in device["entities"]:
            self._add_entity(item, entity, words)
        item.setExpanded(f"device:{device['id']}" in expanded)

    def _add_entity(self, parent, entity, words):
        child = QTreeWidgetItem(parent, [
            f"{ha_home.icon_for(entity)} {entity.get('name') or entity.get('id')}",
            ha_home.value_text(entity, words)])
        child.setData(COL_NAME, ROLE_KEY, f"entity:{entity.get('id')}")
        child.setToolTip(COL_NAME, entity.get("id", ""))
        if not ha_home.available(entity):
            child.setForeground(COL_STATE, FADED)
        if entity.get("domain") in ha_home.TOGGLE_DOMAINS and ha_home.available(entity):
            self._toggle_button(child, entity["id"])

    def _toggle_button(self, item, entity_id):
        button = QToolButton()
        button.setText("⏻")
        button.setAutoRaise(True)
        button.setToolTip(tr("Switch {entity} on or off").format(entity=entity_id))
        button.clicked.connect(lambda _=False, e=entity_id: self.toggle(e))
        self.tree.setItemWidget(item, COL_ACTION, button)

    def toggle(self, entity_id):
        client = self._ha()
        if client is None:
            return
        domain = entity_id.split(".", 1)[0]

        def done(_data):
            QTimer.singleShot(800, self.refresh)   # the new state, once applied

        def failed(error):
            self.lbl_status.setText(tr("Could not switch {entity}: {error}").format(
                entity=entity_id, error=error))
        client.post(f"/services/{domain}/toggle", {"entity_id": entity_id}, done, failed)
