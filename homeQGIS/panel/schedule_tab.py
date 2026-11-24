"""Schedule tab of the panel: Valetudo's timers, week view, one-off cleanings."""

import time

from qgis.PyQt.QtCore import QDateTime, Qt, QTime
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QTimeEdit,
    QLabel,
    QMessageBox,
    QTreeWidgetItem,
)
from qgis.core import QgsSettings

from ..core.i18n import tr
from ..valetudo import schedule
from ..valetudo.schedule_view import WeekView
from ..valetudo.timer_dialog import TimerDialog, day_names, format_offset, utc_offset_minutes
from .common import (KEY_ONCE_TIMERS, preset_labels)

ONCE_GRACE_S = 3600                          # deleted an hour after their start time


class ScheduleMixin:
    """Part of ValetudoPanel (see status_panel.py)."""

    def _build_schedule(self):
        """Schedule: Valetudo's timers (run by the robot); read when the tab is shown."""
        self._timers, self._timer_props = [], None
        self.week = WeekView()
        self.week.drop_source = self.rooms
        self.week_layout.addWidget(self.week)
        self.week.timerClicked.connect(self._select_timer)
        self.week.timerDoubleClicked.connect(lambda timer_id: (self._select_timer(timer_id),
                                                               self._edit_timer()))
        self.week.slotDoubleClicked.connect(self._new_timer_at)
        self.week.groupDropped.connect(self._new_timer_for_group)
        self.timers.itemChanged.connect(self._on_timer_item_changed)
        self.timers.itemDoubleClicked.connect(lambda *_: self._edit_timer())
        self.timers.itemSelectionChanged.connect(self._update_timer_buttons)
        self.timers.itemSelectionChanged.connect(
            lambda: self.week.set_selected(self._selected_timer_id()))
        self.btn_timer_new.clicked.connect(self._new_timer)
        self.btn_timer_edit.clicked.connect(self._edit_timer)
        self.btn_timer_delete.clicked.connect(self._delete_timer)
        self.btn_timer_run.clicked.connect(self._run_timer)
        self.btn_tonight.clicked.connect(self._tonight)
        self.segmentsChanged.connect(lambda *_: self._render_timers())
        self._render_timers()

    def _update_schedule(self):
        """Read the timers each time the Schedule tab is shown."""
        if self.client is None or not self.isVisible() \
                or not self._page_shown(self.tab_schedule):
            return
        self.client.fetch_timers()
        if self._timer_props is None:
            self.client.fetch_timer_properties()

    def _on_timer_properties(self, properties):
        self._timer_props = properties

    def _on_timers(self, timers):
        offset = utc_offset_minutes()
        self._timers = sorted(timers, key=lambda t: schedule.sort_key(t, offset))
        self._render_timers()
        self._remove_done_once_timers()

    def _days_text(self, days):
        days = set(days)
        if len(days) == 7:
            return tr("Every day")
        if days == {1, 2, 3, 4, 5}:
            return tr("Weekdays")
        if days == {0, 6}:
            return tr("Weekends")
        names = day_names()
        return " ".join(names[d] for d in sorted(days, key=lambda d: (d - 1) % 7))

    def _cleaning_text(self, timer):
        action = timer.get("action") or {}
        params = action.get("params") or {}
        if action.get("type") == "segment_cleanup":
            text = ", ".join(self.rooms_ctl.name(i) for i in params.get("segment_ids") or [])
            if int(params.get("iterations") or 1) > 1:
                text += f" ×{int(params['iterations'])}"
        elif action.get("type") == "full_cleanup":
            text = tr("Whole home")
        else:
            text = action.get("type") or "?"
        labels = preset_labels()
        extras = [labels.get(v, v) for v in schedule.pre_action_values(timer).values() if v]
        return " · ".join([text] + extras)

    def _render_timers(self):
        offset = utc_offset_minutes()
        selected = self._selected_timer_id()
        self.timers.blockSignals(True)
        self.timers.clear()
        for timer in self._timers:
            days, hour, minute = schedule.local_schedule(timer, offset)
            item = QTreeWidgetItem([timer.get("label") or tr("(no name)"), self._days_text(days),
                                    f"{hour:02d}:{minute:02d}", self._cleaning_text(timer)])
            item.setData(0, Qt.ItemDataRole.UserRole, timer.get("id"))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                          | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemNeverHasChildren)
            item.setCheckState(0, Qt.CheckState.Checked if timer.get("enabled")
                               else Qt.CheckState.Unchecked)
            item.setToolTip(3, item.text(3))
            self.timers.addTopLevelItem(item)
            if timer.get("id") == selected:
                item.setSelected(True)
        self.timers.blockSignals(False)
        for column in range(3):
            self.timers.resizeColumnToContents(column)
        entries = []
        for timer in self._timers:
            days, hour, minute = schedule.local_schedule(timer, offset)
            entries.append((timer.get("id"), timer.get("label") or tr("(no name)"),
                            days, hour, minute, bool(timer.get("enabled"))))
        self.week.set_entries(entries, day_names())
        self.week.set_selected(selected)
        self.lbl_timers_note.setText(
            tr("Run by the robot itself, even when QGIS is closed. Local times ({offset}).")
            .format(offset=format_offset(offset)) if self.client is not None
            else tr("Not connected."))
        self._update_timer_buttons()

    def _selected_timer_id(self):
        items = self.timers.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _selected_timer(self):
        timer_id = self._selected_timer_id()
        return next((t for t in self._timers if t.get("id") == timer_id), None)

    def _update_timer_buttons(self, *_):
        connected = self.client is not None
        selected = self._selected_timer() is not None
        self.btn_timer_new.setEnabled(connected)
        for button in (self.btn_timer_edit, self.btn_timer_delete, self.btn_timer_run):
            button.setEnabled(connected and selected)

    def _on_timer_item_changed(self, item, column):
        """The checkbox turns a timer on or off (saved on the robot at once)."""
        timer_id = item.data(0, Qt.ItemDataRole.UserRole)
        timer = next((t for t in self._timers if t.get("id") == timer_id), None)
        enabled = item.checkState(0) == Qt.CheckState.Checked
        if column != 0 or timer is None or self.client is None \
                or bool(timer.get("enabled")) == enabled:
            return
        timer["enabled"] = enabled
        self.client.save_timer(timer)

    def _open_timer_dialog(self, timer):
        dialog = TimerDialog(self, timer, self._segments, getattr(self, "_room_groups", []),
                             self.client, self.capabilities, self._timer_props)
        if dialog.exec() and self.client is not None:
            self.client.save_timer(dialog.timer())

    def _select_timer(self, timer_id):
        for i in range(self.timers.topLevelItemCount()):
            item = self.timers.topLevelItem(i)
            item.setSelected(item.data(0, Qt.ItemDataRole.UserRole) == timer_id)
        self.week.set_selected(timer_id)

    def _new_timer_at(self, dow, hour, minute, segment_ids=None, label=""):
        """New cleaning at a slot of the week view (local time), rooms pre-ticked."""
        if self.client is None:
            return
        self._open_timer_dialog(schedule.build_timer(
            None, label, [dow], hour, minute, utc_offset_minutes(), segment_ids=segment_ids,
            iterations=self.passes()))

    def _dragged_rooms(self):
        """(room ids, group title) of the line being dragged from the rooms tree."""
        item = self.rooms.currentItem()
        if item is None:
            return [], ""
        seg_id = item.data(0, Qt.ItemDataRole.UserRole)
        if seg_id is not None:
            return [seg_id], item.text(0)
        ids = [item.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(item.childCount())]
        return [i for i in ids if i is not None], item.text(0)

    def _new_timer_for_group(self, dow, hour, minute):
        ids, title = self._dragged_rooms()
        if ids:
            self._new_timer_at(dow, hour, minute, ids, title[:24])

    def _tonight(self, *_):
        """Clean the ticked rooms (or the whole home) once, tonight: a timer for today
        that the plugin deletes once its time is past."""
        if self.client is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Tonight"))
        form = QFormLayout(dialog)
        when = QTimeEdit(QTime(22, 0))
        when.setDisplayFormat("HH:mm")
        form.addRow(tr("Start at"), when)
        ids = self.rooms_ctl.checked_ids(ticked_order=True)
        names = ", ".join(self.rooms_ctl.name(i) for i in ids) or tr("Whole home")
        form.addRow(tr("Clean"), QLabel(names))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if not dialog.exec():
            return
        start = QDateTime.currentDateTime()
        start.setTime(when.time())
        if start <= QDateTime.currentDateTime():
            start = start.addDays(1)   # already past today: tomorrow
        dow = start.date().dayOfWeek() % 7          # Qt: 1 = Monday … 7 = Sunday
        label = tr("Once {date}").format(date=start.toString("dd/MM HH:mm"))[:24]
        timer = schedule.build_timer(None, label, [dow], when.time().hour(),
                                     when.time().minute(), utc_offset_minutes(),
                                     segment_ids=ids or None, iterations=self.passes())
        once = QgsSettings().value(KEY_ONCE_TIMERS, [], type=list) or []
        once.append(f"{label}|{start.toSecsSinceEpoch()}")
        QgsSettings().setValue(KEY_ONCE_TIMERS, once)
        self.client.save_timer(timer)

    def _remove_done_once_timers(self):
        """Delete the one-off cleanings ("Tonight") whose time is past by an hour."""
        once = QgsSettings().value(KEY_ONCE_TIMERS, [], type=list) or []
        if not once or self.client is None:
            return
        now, keep = time.time(), []
        labels = {t.get("label"): t.get("id") for t in self._timers}
        for entry in once:
            label, _, due = entry.rpartition("|")
            if not due.isdigit() or label not in labels:
                continue           # unknown or already gone: forget it
            if now > int(due) + ONCE_GRACE_S:
                self.client.delete_timer(labels[label])
            else:
                keep.append(entry)
        QgsSettings().setValue(KEY_ONCE_TIMERS, keep)

    def _new_timer(self, *_):
        if self.client is not None:
            self._open_timer_dialog(schedule.new_timer())

    def _edit_timer(self, *_):
        timer = self._selected_timer()
        if timer is not None and self.client is not None:
            self._open_timer_dialog(dict(timer))

    def _delete_timer(self, *_):
        timer = self._selected_timer()
        if timer is None or self.client is None:
            return
        name = timer.get("label") or tr("(no name)")
        if QMessageBox.question(
                self, tr("Delete scheduled cleaning"),
                tr("Delete “{name}” from the robot?").format(name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.client.delete_timer(timer["id"])

    def _run_timer(self, *_):
        timer = self._selected_timer()
        if timer is None or self.client is None:
            return
        name = timer.get("label") or tr("(no name)")
        if QMessageBox.question(
                self, tr("Run scheduled cleaning now"),
                tr("Start “{name}” now?").format(name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.client.run_timer(timer["id"])
