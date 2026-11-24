"""Clean tab of the panel: rooms, presets, room menu."""

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QAbstractItemView, QInputDialog, QMenu, QMessageBox
from qgis.core import QgsSettings

from ..core.i18n import tr
from ..core.icons import icon
from ..map import room_groups
from ..map.rooms_tree import RoomsTree
from .common import (KEY_GOTO_QUIET, preset_labels)

class CleanMixin:
    """Part of ValetudoPanel (see status_panel.py)."""

    def _build_clean(self):
        """Clean."""
        # Rooms in a checkable tree: "All rooms" (tri-state) above one checkbox per
        # room. Right-click a room to rename, join or split it.
        self.rooms_ctl = RoomsTree(self.rooms, expanded_key="valetudo/room_group_open")
        self.rooms_ctl.checkedChanged.connect(self._update_rooms_button)
        self.rooms.customContextMenuRequested.connect(self._on_rooms_context_menu)
        self.rooms.setVisible(False)
        self.rooms.setDragEnabled(True)   # a group can be dropped on the week view
        self.rooms.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.btn_rooms.setIcon(icon("clean_rooms"))
        self.btn_rooms.clicked.connect(self._clean_rooms)
        self.btn_rooms.setVisible(False)
        self._segments = []
        # Shown only for robots whose "Go to" is a small cleaning job (no native go-to).
        self.chk_goto_quiet.setChecked(QgsSettings().value(KEY_GOTO_QUIET, True, type=bool))
        self.chk_goto_quiet.toggled.connect(
            lambda checked: QgsSettings().setValue(KEY_GOTO_QUIET, checked))
        self.chk_goto_quiet.setVisible(False)
        self.preset_combos = {"FanSpeedControlCapability": self.combo_fan_speed,
                              "WaterUsageControlCapability": self.combo_water_usage,
                              "OperationModeControlCapability": self.combo_operation_mode}
        for capability, combo in self.preset_combos.items():
            combo.activated.connect(lambda index, c=capability: self._on_preset_chosen(c, index))

    def _on_segments(self, segments):
        rows = []
        for seg in segments:
            if isinstance(seg, dict) and seg.get("id") is not None:
                seg_id = str(seg["id"])
                rows.append((seg_id, seg.get("name") or f"{tr('Room')} {seg_id}"))
        rows.sort(key=lambda r: r[1].lower())
        if rows == self._segments:
            return
        self._segments = rows
        self.rooms_ctl.set_rooms(rows)
        self.rooms.setVisible(bool(rows))
        self._update_rooms_button()
        self.segmentsChanged.emit(rows)

    def set_room_groups(self, groups):
        """Groups from the room groups file: [(title, [entry, …]), …]."""
        self._room_groups = list(groups)
        self.rooms_ctl.set_groups(groups)

    @property
    def _checked_rooms(self):
        return set(self.rooms_ctl.checked)

    def _on_rooms_context_menu(self, pos):
        item = self.rooms.itemAt(pos)
        seg_id = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        global_pos = self.rooms.viewport().mapToGlobal(pos)
        if seg_id is not None:   # a room
            self._room_menu(seg_id, item.text(0), global_pos)
        else:                    # a group line or empty space
            menu = QMenu(self)
            menu.addAction(tr("Edit room groups…"), self.edit_room_groups)
            menu.exec(global_pos)

    def toggle_room(self, seg_id):
        """From the map: tick or untick a room in the Clean tab."""
        ids = list(self.rooms_ctl.checked)
        ids = [i for i in ids if i != seg_id] if seg_id in ids else ids + [seg_id]
        self.rooms_ctl.set_checked(ids)
        self.show_feedback(tr("Ticked: {rooms}").format(
            rooms=", ".join(self.rooms_ctl.name(i) for i in ids) or "—"))

    def room_menu(self, seg_id, name, global_pos):
        """From the map: the room's menu (rename, join, split)."""
        self._room_menu(seg_id, name or self.rooms_ctl.name(seg_id), global_pos)

    def edit_room_groups(self, *_):
        """Open the room groups file in the system's text editor (created if needed)."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(room_groups.ensure_file()))

    def _room_menu(self, seg_id, name, global_pos):
        if self.client is None:
            return
        caps = self.capabilities
        can_rename = caps is None or "MapSegmentRenameCapability" in caps
        can_edit = caps is None or "MapSegmentEditCapability" in caps

        menu = QMenu(self)
        rename = menu.addAction(tr("Rename…"))
        rename.setEnabled(can_rename)
        rename.triggered.connect(lambda *_: self._rename_room(seg_id, name))
        join = menu.addMenu(tr("Join with"))
        join.setEnabled(can_edit and len(self._segments) > 1)
        for other_id, other_name in self._segments:
            if other_id != seg_id:
                action = join.addAction(other_name)
                action.triggered.connect(
                    lambda *_, o=other_id, on=other_name: self._join_rooms(seg_id, name, o, on))
        split = menu.addAction(tr("Split with a line on the map…"))
        split.setEnabled(can_edit)
        split.triggered.connect(lambda *_: self.splitRequested.emit(seg_id, name))
        if not can_rename or not can_edit:
            menu.addSeparator()
            note = menu.addAction(tr("Greyed out: not supported by this robot."))
            note.setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Edit room groups…"), self.edit_room_groups)
        menu.exec(global_pos)

    def _rename_room(self, seg_id, name):
        new_name, ok = QInputDialog.getText(self, tr("Rename room"), tr("New name:"), text=name)
        new_name = new_name.strip()
        if ok and new_name and new_name != name and self.client is not None:
            self.client.rename_segment(seg_id, new_name)

    def _join_rooms(self, seg_a, name_a, seg_b, name_b):
        answer = QMessageBox.question(
            self, tr("Join rooms"),
            tr("Join “{a}” and “{b}” into one room?").format(a=name_a, b=name_b),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes and self.client is not None:
            self.rooms_ctl.uncheck({seg_a, seg_b})
            self.client.join_segments(seg_a, seg_b)

    def _update_rooms_button(self):
        """Shown when the robot knows its rooms; says how many are ticked."""
        supported = self.capabilities is None or "MapSegmentationCapability" in self.capabilities
        n = len(self._checked_rooms)
        self.btn_rooms.setVisible(bool(self._segments) and supported)
        self.btn_rooms.setText(tr("Clean room(s)"))
        self.btn_rooms.setEnabled(self.client is not None and n > 0)
        self.btn_rooms.setToolTip(tr("Tick rooms above, then click here.") if n == 0
                                  else tr("Clean the {n} ticked room(s).").format(n=n))

    def _clean_rooms(self, *_):
        ids = self.checked_room_ids()
        if self.client is not None and ids:
            self.client.clean_segments(ids, self.passes())

    def passes(self):
        """Number of passes chosen in the Clean tab (rooms and zones)."""
        return self.spin_passes.value()

    def checked_room_ids(self):
        """Ticked rooms, in list order."""
        return self.rooms_ctl.checked_ids()

    def _on_preset_chosen(self, capability, index):
        combo = self.preset_combos[capability]
        name = combo.itemData(index)
        if self.client is not None and name:
            self.client.set_preset(capability, name)

    def _on_presets(self, capability, presets):
        combo = self.preset_combos.get(capability)
        if combo is None:
            return
        current = combo.currentData()
        combo.clear()
        labels = preset_labels()
        for name in presets:
            combo.addItem(labels.get(name, name), name)
        if current is not None:
            combo.setCurrentIndex(max(0, combo.findData(current)))
