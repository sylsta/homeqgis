"""Editor of one Valetudo timer (layout: ``ui/timer_dialog.ui``).

Shows days and time in local time; schedule.build_timer() converts to UTC.
Pre-actions (fan speed, water usage, mode) are offered only when both the
timers and the robot support them, with the robot's own preset values.
"""

from qgis.PyQt.QtCore import QDateTime, QLocale, QTime
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

from . import schedule
from .i18n import tr
from .rooms_tree import RoomsTree
from .ui_loader import load_ui, set_row_visible

UI_WIDGETS = (
    "edit_label", "time_edit", "radio_everything", "radio_rooms", "rooms", "chk_custom_order",
    "lbl_order", "spin_iterations", "combo_fan_speed", "combo_water_usage",
    "combo_operation_mode", "chk_enabled", "lbl_note", "button_box", "timer_form",
    *(f"chk_day_{i}" for i in range(1, 8)),
)


def utc_offset_minutes():
    """Current offset of local time from UTC, in minutes (Paris in winter: 60)."""
    return QDateTime.currentDateTime().offsetFromUtc() // 60


def format_offset(minutes):
    sign = "+" if minutes >= 0 else "−"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "")


def day_names():
    """{Valetudo day (0 = Sunday): short local name}, in display order (Monday first)."""
    locale = QLocale()
    return {qt_day % 7: locale.dayName(qt_day, QLocale.FormatType.ShortFormat)
            for qt_day in range(1, 8)}


class TimerDialog(QDialog):
    def __init__(self, parent, timer, rows, groups, client, capabilities=None, properties=None):
        """timer: the Valetudo timer to edit (schedule.new_timer() for a new one).
        rows: [(room id, name)]; groups: room groups; properties: GET /timers/properties."""
        super().__init__(parent)
        load_ui("timer_dialog.ui", self, UI_WIDGETS)
        self._timer = timer
        self._client = client
        self._offset = utc_offset_minutes()
        properties = properties or {}
        actions = properties.get("supportedActions") or ["full_cleanup", "segment_cleanup"]
        pre_actions = properties.get("supportedPreActions") or []

        # Days, Monday first, with the locale's names.
        self._day_boxes = {}
        for i, (dow, name) in enumerate(sorted(day_names().items(),
                                               key=lambda kv: (kv[0] - 1) % 7), start=1):
            box = getattr(self, f"chk_day_{i}")
            box.setText(name)
            self._day_boxes[dow] = box
        days, hour, minute = schedule.local_schedule(timer, self._offset)
        for dow, box in self._day_boxes.items():
            box.setChecked(dow in days)
        self.time_edit.setTime(QTime(hour, minute))
        self.edit_label.setText(timer.get("label") or "")
        self.chk_enabled.setChecked(bool(timer.get("enabled", True)))

        # What: whole home or rooms (the same tree as the panel's).
        self.rooms_ctl = RoomsTree(self.rooms)
        self.rooms_ctl.set_rooms(rows)
        self.rooms_ctl.set_groups(groups)
        action = timer.get("action") or {}
        params = action.get("params") or {}
        is_rooms = action.get("type") == "segment_cleanup"
        self.rooms_ctl.set_checked(params.get("segment_ids") or [])
        self.spin_iterations.setValue(int(params.get("iterations") or 1))
        self.chk_custom_order.setChecked(bool(params.get("custom_order")))
        rooms_ok = "segment_cleanup" in actions and bool(rows)
        self.radio_rooms.setEnabled(rooms_ok)
        if not rooms_ok:
            self.radio_rooms.setToolTip(tr("The robot does not know its rooms yet."))
        (self.radio_rooms if is_rooms and rooms_ok else self.radio_everything).setChecked(True)
        self.radio_rooms.toggled.connect(self._update_what)
        self.rooms_ctl.checkedChanged.connect(self._update_order)
        self.chk_custom_order.toggled.connect(self._update_order)
        self._update_what()

        # Settings applied before the cleaning: robot's own presets, "unchanged" first.
        self._preset_combos = {
            "fan_speed_control": self.combo_fan_speed,
            "water_usage_control": self.combo_water_usage,
            "operation_mode_control": self.combo_operation_mode,
        }
        self._wanted = schedule.pre_action_values(timer)
        for kind, combo in self._preset_combos.items():
            capability = schedule.PRE_ACTION_CAPABILITIES[kind]
            supported = kind in pre_actions and (capabilities is None or capability in capabilities)
            set_row_visible(self.timer_form, combo, supported)
            combo.addItem(tr("Unchanged"), None)
            self._add_value(combo, self._wanted.get(kind))   # until the presets arrive
            if supported and client is not None:
                client.fetch_presets(capability, quiet=True)
        if client is not None:
            client.presetsReceived.connect(self._on_presets)

        self.lbl_note.setText(tr(
            "Run by the robot itself, even when QGIS is closed. Times are local ({offset}); "
            "Valetudo stores them in UTC, so after a change to or from summer time the "
            "cleaning starts one hour off until it is saved again.").format(
                offset=format_offset(self._offset)))
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.finished.connect(self._disconnect)

    def _disconnect(self, *_):
        if self._client is not None:
            try:
                self._client.presetsReceived.disconnect(self._on_presets)
            except (TypeError, RuntimeError):
                pass

    def _on_presets(self, capability, presets):
        from .status_panel import preset_labels   # here: status_panel imports this module
        kind = next((k for k, c in schedule.PRE_ACTION_CAPABILITIES.items() if c == capability),
                    None)
        combo = self._preset_combos.get(kind)
        if combo is None:
            return
        labels = preset_labels()
        current = combo.currentData()   # what is shown now (saved value or user's choice)
        combo.clear()
        combo.addItem(tr("Unchanged"), None)
        for name in presets:
            combo.addItem(labels.get(name, name), name)
        self._add_value(combo, current)

    @staticmethod
    def _add_value(combo, value):
        """Select value, adding it if the robot does not list it (kept as saved)."""
        if value is None:
            return
        if combo.findData(value) < 0:
            from .status_panel import preset_labels
            combo.addItem(preset_labels().get(value, value), value)
        combo.setCurrentIndex(combo.findData(value))

    def _update_what(self, *_):
        rooms = self.radio_rooms.isChecked()
        for widget in (self.rooms, self.chk_custom_order, self.spin_iterations):
            widget.setEnabled(rooms)
        self._update_order()

    def _update_order(self, *_):
        ids = self.rooms_ctl.checked_ids(ticked_order=True)
        show = self.radio_rooms.isChecked() and self.chk_custom_order.isChecked() and len(ids) > 1
        self.lbl_order.setVisible(show)
        if show:
            self.lbl_order.setText(tr("Order: {rooms}").format(
                rooms=" → ".join(self.rooms_ctl.name(i) for i in ids)))

    def accept(self):
        if not any(box.isChecked() for box in self._day_boxes.values()):
            QMessageBox.warning(self, self.windowTitle(), tr("Tick at least one day."))
            return
        if self.radio_rooms.isChecked() and not self.rooms_ctl.checked:
            QMessageBox.warning(self, self.windowTitle(), tr("Tick at least one room."))
            return
        super().accept()

    def timer(self):
        """The edited timer, ready to send to Valetudo."""
        days = [dow for dow, box in self._day_boxes.items() if box.isChecked()]
        time = self.time_edit.time()
        rooms = self.radio_rooms.isChecked()
        custom = rooms and self.chk_custom_order.isChecked()
        return schedule.build_timer(
            self._timer, self.edit_label.text(), days, time.hour(), time.minute(), self._offset,
            segment_ids=self.rooms_ctl.checked_ids(ticked_order=custom) if rooms else None,
            iterations=self.spin_iterations.value(), custom_order=custom,
            pre_actions={kind: combo.currentData()
                         for kind, combo in self._preset_combos.items()},
            enabled=self.chk_enabled.isChecked())
